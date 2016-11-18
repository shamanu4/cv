# -*- encoding: utf-8 -*-
from __future__ import print_function, division, unicode_literals, absolute_import

from functools import update_wrapper

from daterange_filter.filter import DateRangeFilter
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.contrib import messages
from django.contrib.admin.utils import quote
from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.template import Template, Context
from django.utils.html import mark_safe
from django.utils.translation import ugettext_lazy as _, ugettext
from django_mptt_admin import util
from django_mptt_admin.admin import DjangoMpttAdmin
from filebrowser.settings import ADMIN_THUMBNAIL
from grappelli_filters import RelatedAutocompleteFilter, FiltersMixin

from base.models import Unit, ItemCategory, Place, PurchaseItem, Payer, Purchase, Item, ItemSerial, ItemChunk, \
    TransactionItem, Transaction, OrderItemSerial, ContractItemSerial, VItemMovement, VSerialMovement, \
    get_descendants_ids, FixSerialTransform, FixCategoryMerge, FixPlaceMerge, Cell, GeoName, Transmutation, \
    Warranty, Return
from .actions import process_to_void, update_cell
from .filters import MPTTRelatedAutocompleteFilter
from .forms import ItemCategoryForm, PlaceForm, PurchaseItemForm, TransactionItemForm, PurchaseForm, TransactionForm, \
    FixCategoryMergeForm, FixPlaceMergeForm, CellForm, CellItemActionForm, ItemInlineForm, ItemChunkForm, \
    ItemSerialForm, TransmutationForm, WarrantyForm, WarrantyInlineForm, ReturnForm
from .functions import create_model_admin
from .inlines import ItemCategoryCommentInline, PurchaseItemInline, PurchaseItemInlineReadonly, \
    TransactionItemInlineReadonly, TransactionItemInline, TransactionCommentPlaceInline, TransmutationItemInline, \
    TransmutationItemInlineReadonly, ReturnItemInline, ReturnItemInlineReadonly
from .overrides import AdminReadOnly, InlineReadOnly, HiddenAdminModelMixin

try:
    from urllib import urlencode
except ImportError:
    from urllib.parse import urlencode


@admin.register(GeoName)
class GeoNameAdmin(admin.ModelAdmin):
    search_fields = ['name']
    readonly_fields = ['timestamp', ]
    list_display = ['name', 'timestamp']
    list_filter = [('timestamp', DateRangeFilter), ]


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    search_fields = ['name']


@admin.register(ItemCategory)
class ItemCategoryAdmin(DjangoMpttAdmin):
    class Media:
        js = ('base/js/category_parent_autocomplete.js',)

    change_tree_template = u'admin/mptt_change_list.html'
    form = ItemCategoryForm
    search_fields = ['name', ]
    tree_auto_open = False
    inlines = [ItemCategoryCommentInline]
    list_display = ['name', 'image_thumbnail', 'timestamp']
    list_filter = [('timestamp', DateRangeFilter), ]
    readonly_fields = ['timestamp', ]

    def image_thumbnail(self, obj):
        if obj.photo:
            if obj.photo.filetype == "Image":
                return '<a href="%s"><img src="%s" /></a>' % (
                obj.photo.url, obj.photo.version_generate(ADMIN_THUMBNAIL).url)
            else:
                return '<a href="%s">%s</a>' % (obj.photo.url, obj.photo.url)
        else:
            return ""

    image_thumbnail.allow_tags = True
    image_thumbnail.short_description = "Thumbnail"

    def get_tree_data(self, qs, max_level):
        pk_attname = self.model._meta.pk.attname

        def handle_create_node(instance, node_info):
            pk = quote(getattr(instance, pk_attname))

            if Item.objects.filter(category_id=pk).count():
                node_info.update(
                        view_url=reverse("admin:base_category_item_changelist", args=[pk]),
                        transfer_url=reverse("admin:base_item_movement_filtered_changelist", args=[0, pk]),
                )
            node_info.update(
                    url=self.get_admin_url('change', (quote(pk),)),
                    storage_url=reverse(
                            'admin:base_place_item_changelist',
                            args=(settings.APP_FILTERS["PLACE_STORAGE_ID"],)
                    ) + "?category__id__in=%s" % pk,
                    move_url=self.get_admin_url('move', (quote(pk),))
            )

        return util.get_tree_from_queryset(qs, handle_create_node, max_level)


@admin.register(Place)
class PlaceAdmin(DjangoMpttAdmin):
    change_tree_template = u'admin/mptt_change_list.html'
    search_fields = ['name', ]
    tree_auto_open = False
    form = PlaceForm
    list_display = ['name', 'is_shop', 'items_changelist_link', 'timestamp']
    list_filter = [('timestamp', DateRangeFilter), ]
    readonly_fields = ['timestamp', ]

    def items_changelist_link(self, obj):
        link = reverse("admin:base_place_item_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("items list")))

    def get_tree_data(self, qs, max_level):
        pk_attname = self.model._meta.pk.attname

        def handle_create_node(instance, node_info):
            pk = quote(getattr(instance, pk_attname))

            if Item.objects.filter(place_id=pk).count():
                node_info.update(
                        view_url=reverse("admin:base_place_item_changelist", args=[pk]),
                        transfer_url=reverse("admin:base_item_movement_filtered_changelist", args=[pk]),
                )
            node_info.update(
                    url=self.get_admin_url('change', (quote(pk),)),
                    move_url=self.get_admin_url('move', (quote(pk),))
            )

        return util.get_tree_from_queryset(qs, handle_create_node, max_level)


@admin.register(PurchaseItem)
class PurchaseItemAdmin(HiddenAdminModelMixin, AdminReadOnly):
    pass


@admin.register(Payer)
class PayerAdmin(admin.ModelAdmin):
    search_fields = ['name', ]


@admin.register(Purchase)
class PurchaseAdmin(FiltersMixin, admin.ModelAdmin):
    class Media:
        js = ('base/js/purchase_source_item_autocomplete.js',)

    form = PurchaseForm
    inlines = [PurchaseItemInline, ]
    list_display = ['__str__', 'created_at', 'completed_at', 'source', 'destination', 'is_completed',
                    'is_prepared', ]
    list_filter = [
        ('source', MPTTRelatedAutocompleteFilter),
        ('destination', MPTTRelatedAutocompleteFilter),
        'is_completed', 'is_prepared',
    ]
    search_fields = ['source__name', 'destination__name', 'purchase_items__category__name']

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_completed:
            return False
        else:
            return super(PurchaseAdmin, self).has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if obj and obj.is_completed:
            readonly_fields.extend(['source', 'destination', 'completed_at', 'is_auto_source'])
            dir(self.form)
        return readonly_fields

    def get_fields(self, request, obj=None):
        fields = super(PurchaseAdmin, self).get_fields(request, obj)
        if obj and obj.is_completed:
            fields.remove('force_complete')
        return fields

    def get_inline_instances(self, request, obj=None):
        inline_instances = []

        if obj and obj.is_completed:
            inlines = [PurchaseItemInlineReadonly, ]
        else:
            inlines = self.inlines

        self._obj = obj

        for inline_class in inlines:
            inline = inline_class(self.model, self.admin_site)
            inline_instances.append(inline)
        return inline_instances

    def save_formset(self, request, form, formset, change):
        print(change)
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if formset.form.__name__ == PurchaseItemForm.__name__ and instance.purchase.is_completed:
                completed_instance = PurchaseItem.objects.get(pk=instance.pk)
                if not completed_instance.pk == instance.pk or \
                        not completed_instance.quantity == instance.quantity or \
                        not completed_instance.category == instance.category or \
                        not completed_instance.serials == instance.serials:
                    raise ValidationError(ugettext("purchase items data is read only!"))
            instance.save()
        formset.save_m2m()
        if self._obj:
            p = self._obj
            if hasattr(p, "is_pending") and p.is_pending:
                # print "complete pending purchase"
                p.is_pending = False
                p.complete()


@admin.register(Item)
class ItemAdmin(FiltersMixin, AdminReadOnly):
    search_fields = ['category__name', 'place__name']
    list_filter = [('category', MPTTRelatedAutocompleteFilter), 'cell']
    list_display = ['category_name', 'quantity', 'place', 'cell']


@admin.register(ItemSerial)
class ItemSerialAdmin(FiltersMixin):
    class Media:
        # js = ('base/js/place_item_changelist_autocomplete.js',)
        js = ('base/js/serial_purchase_autocomplete.js',)

    form = ItemSerialForm

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.pk:
            result = list(set(
                    [field.name for field in self.opts.local_fields] +
                    [field.name for field in self.opts.local_many_to_many]
            ))
            if 'id' in result:
                result.remove('id')
            return result
        return super(ItemSerialAdmin, self).get_readonly_fields(request, obj)

    def get_queryset(self, request):
        return super(ItemSerialAdmin, self).get_queryset(request).select_related('item', 'item__category',
                                                                                 'item__place')

    def owner(self, instance):
        return instance.item.place.name

    def serial_movement_changelist_link(self, obj):
        link = reverse("admin:base_serial_movement_filtered_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("movement history")))

    def get_list_display(self, request):
        list_display = self.list_display[:]
        if request.user.has_perm('base.view_item_price'):
            list_display.append('price')
        return list_display

    search_fields = ['item__category__name', 'serial']
    list_filter = [
        ('item__category', MPTTRelatedAutocompleteFilter),
        ('item__place', MPTTRelatedAutocompleteFilter),
        'cell'
    ]
    list_display = ['serial', 'category_name', 'owner', 'cell', 'serial_movement_changelist_link']


@admin.register(ItemChunk)
class ItemChunkAdmin(FiltersMixin, AdminReadOnly):
    search_fields = ['item__category__name']
    list_filter = [
        ('item__category', MPTTRelatedAutocompleteFilter),
        ('item__place', MPTTRelatedAutocompleteFilter),
    ]
    list_display = ['__str__', 'category_name', 'place_name', 'cell']
    form = ItemChunkForm
    actions = [update_cell]
    action_form = CellItemActionForm

    def get_readonly_fields(self, request, obj=None):
        fields = super(ItemChunkAdmin, self).get_readonly_fields(request, obj)
        fields.remove('cell')
        return fields


@admin.register(TransactionItem)
class TransactionItemAdmin(HiddenAdminModelMixin, AdminReadOnly):
    pass


@admin.register(Transaction)
class TransactionAdmin(FiltersMixin, admin.ModelAdmin):
    class Media:
        js = ('base/js/transaction_source_item_autocomplete.js',)

    form = TransactionForm
    list_display = [
        '__str__', 'created_at', 'completed_at',
        'source', 'destination', 'is_completed', 'is_prepared',
        # 'is_negotiated_source', 'is_negotiated_destination', 'is_confirmed_source',
        # 'is_confirmed_destination'
    ]
    list_filter = [
        ('source', MPTTRelatedAutocompleteFilter),
        ('destination', MPTTRelatedAutocompleteFilter),
        'is_completed', 'is_prepared',
        # 'is_negotiated_source', 'is_negotiated_destination', 'is_confirmed_source',
        # 'is_confirmed_destination'
    ]
    search_fields = ['source__name', 'destination__name', 'transaction_items__category__name']
    inlines = [
        TransactionItemInline, TransactionCommentPlaceInline
    ]

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_completed:
            return False
        else:
            return super(TransactionAdmin, self).has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if obj and obj.is_completed:
            readonly_fields.extend(['source', 'destination', 'completed_at'])
        return readonly_fields

    def get_fields(self, request, obj=None):
        fields = super(TransactionAdmin, self).get_fields(request, obj)
        if obj and obj.is_completed:
            fields.remove('force_complete')
        return fields

    def get_inline_instances(self, request, obj=None):
        inline_instances = []

        if obj and obj.is_completed:
            inlines = [TransactionItemInlineReadonly, ]
        else:
            inlines = self.inlines

        self._obj = obj

        for inline_class in inlines:
            inline = inline_class(self.model, self.admin_site)
            inline_instances.append(inline)
        return inline_instances

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if formset.form.__name__ == TransactionItemForm.__name__ and instance.transaction.is_completed:
                err = 1
                for ti in instance.transaction.transaction_items.all():
                    if ti.pk == instance.pk:
                        err = 0
                if err:
                    raise ValidationError(ugettext("transaction items data is read only!"))
            else:
                trash = getattr(instance, "trash", False)
                if not trash:
                    instance.save()
                elif instance.pk:
                    instance.delete()
        formset.save_m2m()
        if self._obj:
            t = self._obj
            if hasattr(t, "is_pending") and t.is_pending:
                # print "complete pending transaction"
                t.is_pending = False
                t.complete()

    def rollback(self, request, queryset):
        for t in queryset:
            if not t.is_completed:
                self.message_user(request,
                                  _("Transaction {trans} not completed. cannot rollback".format(trans=t)),
                                  level=messages.ERROR)
            else:
                for ti in t.transaction_items.all():
                    t = Transaction.objects.create(source=ti.destination, destination=ti.transaction.source)
                    ti.pk = None
                    ti.transaction = t
                    ti.destination = None
                    ti.save()
                    t.force_complete()

    rollback.short_description = _('rollback')

    actions = [rollback]


class PlaceItemAdmin(HiddenAdminModelMixin, ItemAdmin):
    class Media:
        js = ('base/js/place_item_changelist_autocomplete.js',)

    list_filter = [('category', MPTTRelatedAutocompleteFilter), 'cell']
    tpl = Template("{{ form.as_p }}")
    list_display = ['category_name', 'quantity', 'place', 'items_serials_changelist_link',
                    'items_chunks_changelist_link',
                    'item_movement_changelist_link']

    action_form = CellItemActionForm
    actions = [update_cell]

    def __init__(self, *args, **kwargs):
        super(PlaceItemAdmin, self).__init__(*args, **kwargs)
        self.place_id = None
        self.place = None
        self.show_zero = None

    def items_serials_changelist_link(self, obj):
        link = reverse("admin:base_item_serials_filtered_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("serials list")))

    items_serials_changelist_link.short_description = _("serials")

    def items_chunks_changelist_link(self, obj):
        link = reverse("admin:base_item_chunks_filtered_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("chunks list")))

    items_chunks_changelist_link.short_description = _("chunks")

    def item_movement_changelist_link(self, obj):
        link = reverse("admin:base_item_movement_filtered_changelist", args=[self.place_id, obj.category_id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("movement history")))

    item_movement_changelist_link.short_description = _("movement history")

    def custom_cell(self, obj):
        cell_list = list(set(obj.serials.filter(cell__isnull=False).values_list("cell__name", flat=True)))
        if len(cell_list) > 1:
            # or (cell_list and obj.cell is not None and not obj.cell.name == cell_list[0]):
            return "+".join(sorted(cell_list))
        f = ItemInlineForm(instance=obj, auto_id='id_item_' + str(obj.pk) + '_%s')
        html = self.tpl.render(Context({"form": f}))
        return mark_safe('<span class="autocomplete-wrapper-js" '
                         'data-url="/base/ajax/item_cell" data-item-id="%s">%s</span>' % (obj.pk, html))

    def get_queryset(self, request):
        qs = super(PlaceItemAdmin, self).get_queryset(request)
        qs = qs.filter(place_id=self.place_id)
        if not self.show_zero:
            qs = qs.filter(quantity__gt=0)
        return qs

    def get_list_display(self, request):
        list_display = self.list_display[:]
        if self.place.has_cells and 'custom_cell' not in self.list_display:
            list_display.append('custom_cell')
        if request.user.has_perm('base.view_item_price'):
            list_display.append('price')
        return list_display

    def changelist_view(self, request, place_id, extra_context=None):  # pylint:disable=arguments-differ
        request.GET._mutable = True
        self.show_zero = int(request.GET.pop("show_zero", ["0"])[0])
        request.GET.pop("a", None)
        self.place_id = place_id
        extra_context = extra_context or {}
        try:
            place = Place.objects.get(pk=place_id)
        except Place.DoesNotExist:
            extra_context.update({'cl_header': _('Place does not exist')})
        else:
            self.place = place
            cl_header = place.name
            params_get = request.GET.copy()
            params_get.update({'show_zero': int(not self.show_zero)})
            extra_context.update({'show_zero_params': urlencode(params_get)})
            extra_context.update({'show_zero': self.show_zero})
            extra_context.update({'cl_header_addon': _("> ALL")})
            extra_context.update({'cl_header': mark_safe(cl_header)})
        view = super(PlaceItemAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_place_item_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'
    change_form_template = 'admin/proxy_change_form.html'


create_model_admin(PlaceItemAdmin, name='place_item', model=Item)


class CategoryItemAdmin(HiddenAdminModelMixin, ItemAdmin):
    list_display = ['category_name', 'quantity', 'place', 'items_serials_changelist_link',
                    'items_chunks_changelist_link', 'item_movement_changelist_link']

    def __init__(self, *args, **kwargs):
        super(CategoryItemAdmin, self).__init__(*args, **kwargs)
        self.category_id = None
        self.category = None
        self.show_zero = None

    def items_serials_changelist_link(self, obj):
        link = reverse("admin:base_item_serials_filtered_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("serials list")))

    def items_chunks_changelist_link(self, obj):
        link = "#%s" % obj.id
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("chunks list")))

    def item_movement_changelist_link(self, obj):
        link = reverse("admin:base_item_movement_filtered_changelist", args=[0, obj.category_id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("movement history")))

    def get_queryset(self, request):
        qs = super(CategoryItemAdmin, self).get_queryset(request)
        qs = qs.filter(category_id=self.category_id)
        if not self.show_zero:
            qs = qs.filter(quantity__gt=0)
        return qs

    def changelist_view(self, request, category_id, extra_context=None):  # pylint:disable=arguments-differ
        request.GET._mutable = True
        self.show_zero = int(request.GET.pop("show_zero", ["0"])[0])
        request.GET.pop("a", None)
        rq_qs = "?" + (request.GET.urlencode() or "a=1")
        self.category_id = category_id
        extra_context = extra_context or {}
        try:
            category = ItemCategory.objects.get(pk=category_id)
        except ItemCategory.DoesNotExist:
            extra_context.update({'cl_header': _('Category does not exist')})
        else:
            self.category = category
            cl_header = _(u"<{name}> items".format(name=category.name))
            extra_context.update({'show_zero': self.show_zero})
            extra_context.update({'rq_qs': rq_qs})
            extra_context.update({'cl_header': mark_safe(cl_header)})
        view = super(CategoryItemAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_category_item_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'
    change_form_template = 'admin/proxy_change_form.html'


create_model_admin(CategoryItemAdmin, name='category_item', model=Item)


class ItemSerialsFilteredAdmin(HiddenAdminModelMixin, ItemSerialAdmin):
    class Media:
        js = (
            'base/js/place_item_changelist_autocomplete.js',
            'base/js/place_serial_changelist_warranty.js',
        )

    list_display = ['serial', 'category_name', 'serial_movement_changelist_link', 'custom_warranty_date']
    tpl = Template("{{ form.as_p }}")

    def __init__(self, *args, **kwargs):
        super(ItemSerialsFilteredAdmin, self).__init__(*args, **kwargs)
        self.item_id = None
        self.item = None

    def serial_movement_changelist_link(self, obj):
        link = reverse("admin:base_serial_movement_filtered_changelist", args=[obj.id])
        return mark_safe(u'<a href="%s">%s</a>' % (link, _("movement history")))

    serial_movement_changelist_link.short_description = _("movement history")

    def get_queryset(self, request):
        qs = super(ItemSerialsFilteredAdmin, self).get_queryset(request)
        return qs.filter(item_id=self.item_id)

    def get_list_display(self, request):
        list_display = self.list_display[:]
        if self.item.place.has_cells and 'custom_cell' not in self.list_display:
            list_display.append('custom_cell')
        if request.user.has_perm('base.view_item_price'):
            list_display.append('price')
        return list_display

    def changelist_view(self, request, item_id, extra_context=None):  # pylint:disable=arguments-differ
        self.item_id = item_id
        extra_context = extra_context or {}
        try:
            item = Item.objects.get(pk=item_id)
        except Item.DoesNotExist:
            extra_context.update({'cl_header': _('Item does not exist')})
        else:
            self.item = item
            extra_context.update({'cl_header': _(u"Serials for <{name}> in <{place}>".format(
                    name=item.category.name,
                    place=item.place.name
            ))})
        view = super(ItemSerialsFilteredAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    action_form = CellItemActionForm
    actions = [update_cell]

    def custom_cell(self, obj):
        if not obj.item.place.has_cells:
            return obj.cell
        f = ItemInlineForm(instance=obj, auto_id='id_item_' + str(obj.pk) + '_%s')
        html = self.tpl.render(Context({"form": f}))
        return mark_safe('<span class="autocomplete-wrapper-js" '
                         'data-url="/base/ajax/serial_cell" data-item-id="%s">%s</span>' % (obj.pk, html))

    def custom_warranty_date(self, obj):
        try:
            warranty = obj.warranty
        except Warranty.DoesNotExist:
            warranty = None

        f = WarrantyInlineForm(instance=warranty, auto_id='id_warranty_' + str(obj.pk) + '_%s')
        html = self.tpl.render(Context({"form": f}))
        return mark_safe('<span class="date-warranty-wrapper-js" '
                         'data-item-id="%s">' % obj.pk + ''
                                                         '%s' % html + ''
                                                                       '<span class="btn confirm-js"><img src="/static/glyphicons/glyphicons-207-ok-2.png"></span>'
                                                                       '</span>')

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_item_serials_filtered_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'
    change_form_template = 'admin/proxy_change_form.html'


create_model_admin(ItemSerialsFilteredAdmin, name='item_serials_filtered', model=ItemSerial)


class ItemChunksFilteredAdmin(HiddenAdminModelMixin, ItemChunkAdmin):
    class Media:
        js = ('base/js/place_item_changelist_autocomplete.js',)

    item_id = None
    list_display = ['chunk', 'category_name']
    tpl = Template("{{ form.as_p }}")

    def __init__(self, *args, **kwargs):
        super(ItemChunksFilteredAdmin, self).__init__(*args, **kwargs)
        self.item_id = None
        self.item = None

    def get_queryset(self, request):
        qs = super(ItemChunksFilteredAdmin, self).get_queryset(request)
        return qs.filter(item_id=self.item_id)

    def get_list_display(self, request):
        list_display = self.list_display[:]
        if self.item.place.has_cells and 'custom_cell' not in self.list_display:
            list_display.append('custom_cell')
        return list_display

    def changelist_view(self, request, item_id, extra_context=None):  # pylint:disable=arguments-differ
        self.item_id = item_id
        extra_context = extra_context or {}
        try:
            item = Item.objects.get(pk=item_id)
        except Item.DoesNotExist:
            extra_context.update({'cl_header': _('Item does not exist')})
        else:
            self.item = item
            extra_context.update({'cl_header': _(u"Chunks for <{name}> in <{place}>".format(
                    name=item.category.name,
                    place=item.place.name
            ))})
        view = super(ItemChunksFilteredAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    action_form = CellItemActionForm
    actions = [update_cell]

    def custom_cell(self, obj):
        if not obj.item.place.has_cells:
            return obj.cell
        f = ItemInlineForm(instance=obj, auto_id='id_item_' + str(obj.pk) + '_%s')
        html = self.tpl.render(Context({"form": f}))
        return mark_safe('<span class="autocomplete-wrapper-js" '
                         'data-url="/base/ajax/chunk_cell" data-item-id="%s">%s</span>' % (obj.pk, html))

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_item_chunks_filtered_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'
    change_form_template = 'admin/proxy_change_form.html'


create_model_admin(ItemChunksFilteredAdmin, name='item_chunks_filtered', model=ItemChunk)


@admin.register(OrderItemSerial)
class OrderItemSerialAdmin(FiltersMixin, admin.ModelAdmin):
    search_fields = ['serial']
    list_filter = [('item__place', MPTTRelatedAutocompleteFilter), ]
    list_display = ['serial', 'category_name', 'owner', 'comment']
    ordering = ['comment', ]
    readonly_fields = ['item', 'purchase', 'serial', 'owner']
    fields = ['comment', 'serial', 'owner']
    actions = [process_to_void]

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super(OrderItemSerialAdmin, self).get_queryset(request).select_related(
                'item', 'item__category', 'item__place'
        )
        return qs.filter(
                item__category_id__in=get_descendants_ids(ItemCategory, settings.APP_FILTERS["CAT_ORDERS_ID"]),
                item__place_id__in=get_descendants_ids(Place, settings.APP_FILTERS["PLACE_WORKERS_ID"])
        )

    def owner(self, instance):
        return instance.item.place.name


@admin.register(ContractItemSerial)
class ContractItemSerialAdmin(FiltersMixin, admin.ModelAdmin):
    search_fields = ['serial']
    list_filter = [('item__place', MPTTRelatedAutocompleteFilter), ]
    list_display = ['serial', 'category_name', 'owner', 'comment']
    ordering = ['comment', ]
    readonly_fields = ['item', 'purchase', 'serial', 'owner']
    fields = ['comment', 'serial', 'owner']
    actions = [process_to_void]

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super(ContractItemSerialAdmin, self).get_queryset(request).select_related(
                'item', 'item__category', 'item__place'
        )
        return qs.filter(
                item__category_id__in=get_descendants_ids(ItemCategory, settings.APP_FILTERS["CAT_CONTRACTS_ID"]),
                item__place_id__in=get_descendants_ids(Place, settings.APP_FILTERS["PLACE_WORKERS_ID"])
        )

    def owner(self, instance):
        return instance.item.place.name


@admin.register(VItemMovement)
class ItemMovementAdmin(FiltersMixin, AdminReadOnly):
    search_fields = ['destination__name', 'source__name', 'category__name']
    list_filter = (
        ('created_at', DateRangeFilter),
        ('completed_at', DateRangeFilter),
        ('category', MPTTRelatedAutocompleteFilter),
        ('source', MPTTRelatedAutocompleteFilter),
        ('destination', MPTTRelatedAutocompleteFilter),
    )
    list_display = ['item_category_name', 'created_at', 'completed_at', 'source', 'destination', 'quantity', 'price']
    fields = ['item_category_name', 'created_at', 'completed_at', 'source', 'destination', 'quantity']


@admin.register(VSerialMovement)
class SerialMovementAdmin(FiltersMixin, AdminReadOnly):
    search_fields = ['destination__name', 'source__name', 'category__name', 'serial']
    list_filter = (
        ('created_at', DateRangeFilter),
        ('completed_at', DateRangeFilter),
        ('category', MPTTRelatedAutocompleteFilter),
        ('source', MPTTRelatedAutocompleteFilter),
        ('destination', MPTTRelatedAutocompleteFilter),
    )
    list_display = ['serial', 'item_category_name', 'created_at',
                    'completed_at', 'source', 'destination', 'quantity', 'price']
    fields = ['serial', 'item_category_name', 'created_at', 'completed_at',
              'source', 'destination', 'quantity']


class ItemMovementFilteredAdmin(HiddenAdminModelMixin, ItemMovementAdmin):
    place_id = None
    category_id = None

    def get_queryset(self, request):
        qs = super(ItemMovementFilteredAdmin, self).get_queryset(request)
        if self.place_id:
            qs = qs.filter(Q(source_id=self.place_id) | Q(destination_id=self.place_id))
        if self.category_id:
            qs = qs.filter(category_id=self.category_id)
        return qs

    def changelist_view(self, request, place_id=None, category_id=None,
                        extra_context=None):  # pylint:disable=arguments-differ
        self.place_id = int(place_id or "0")
        self.category_id = int(category_id or "0")
        extra_context = extra_context or {}
        try:
            place = Place.objects.get(pk=place_id)
        except Place.DoesNotExist:
            place_name = "any place"
        else:
            place_name = place.name
        if category_id:
            try:
                category = ItemCategory.objects.get(pk=category_id)
            except ItemCategory.DoesNotExist:
                category_name = "any category"
            else:
                category_name = category.name
            extra_context.update({'cl_header': _(u"Movement history for <{category_name}> in <{place_name}>".format(
                    category_name=category_name,
                    place_name=place_name
            ))})
        else:
            extra_context.update({'cl_header': _(u"Movement history for <{place_name}>".format(
                    place_name=place_name
            ))})
        view = super(ItemMovementFilteredAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/(\d+)/$', wrap(self.changelist_view), name='base_item_movement_filtered_changelist'),
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_item_movement_filtered_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'


create_model_admin(ItemMovementFilteredAdmin, name='item_movement_filtered', model=VItemMovement)


class SerialMovementFilteredAdmin(HiddenAdminModelMixin, SerialMovementAdmin):
    place_id = None
    serial_id = None

    def get_queryset(self, request):
        qs = super(SerialMovementFilteredAdmin, self).get_queryset(request)
        qs = qs.filter(serial_id=self.serial_id)
        if self.place_id:
            qs = qs.filter(Q(source_id=self.place_id) | Q(destination_id=self.place_id))
        return qs

    def changelist_view(self, request, serial_id, place_id=None, extra_context=None):  # pylint:disable=arguments-differ
        self.place_id = place_id
        self.serial_id = serial_id
        extra_context = extra_context or {}
        try:
            serial = ItemSerial.objects.get(pk=serial_id)
        except ItemCategory.DoesNotExist:
            serial_name = "unknown serial"
        else:
            serial_name = serial.serial
        if place_id:
            try:
                place = Place.objects.get(pk=place_id)
            except Place.DoesNotExist:
                place_name = "unknown place"
            else:
                place_name = place.name
            extra_context.update({'cl_header': _(u"Movement history for <{serial_name}> in <{place_name}>".format(
                    serial_name=serial_name,
                    place_name=place_name
            ))})
        else:
            extra_context.update({'cl_header': _(u"Movement history for <{serial_name}>".format(
                    serial_name=serial_name,
            ))})
        view = super(SerialMovementFilteredAdmin, self).changelist_view(request, extra_context=extra_context)
        return view

    def get_urls(self):

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            return update_wrapper(wrapper, view)

        urlpatterns = [
            url(r'^(\d+)/(\d+)/$', wrap(self.changelist_view), name='base_serial_movement_filtered_changelist'),
            url(r'^(\d+)/$', wrap(self.changelist_view), name='base_serial_movement_filtered_changelist'),
        ]
        return urlpatterns

    change_list_template = 'admin/proxy_change_list.html'


create_model_admin(SerialMovementFilteredAdmin, name='serial_movement_filtered', model=VSerialMovement)


@admin.register(FixSerialTransform)
class FixSerialTransformAdmin(admin.ModelAdmin):
    search_fields = ['old_serial', 'new_serial']
    list_display = ['timestamp', 'category', 'old_serial', 'new_serial']

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        readonly_fields.extend(['category', 'timestamp'])
        if obj and obj.pk:
            readonly_fields.extend(['old_serial', 'new_serial'])
        return readonly_fields


@admin.register(FixCategoryMerge)
class FixCategoryMergeAdmin(admin.ModelAdmin):
    search_fields = ['old_category_sav_name', 'new_category__name']
    list_display = ['timestamp', 'old_category_sav_name', 'new_category']
    form = FixCategoryMergeForm

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        readonly_fields.extend(['data', 'timestamp', 'old_category_sav_id', 'old_category_sav_name'])
        if obj and obj.pk:
            readonly_fields.extend(['old_category', 'new_category'])
        return readonly_fields


@admin.register(FixPlaceMerge)
class FixPlaceMergeAdmin(admin.ModelAdmin):
    search_fields = ['old_place_sav_name', 'new_place__name']
    list_display = ['timestamp', 'old_place_sav_name', 'new_place']
    form = FixPlaceMergeForm

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        readonly_fields.extend(['timestamp', 'old_place_sav_id', 'old_place_sav_name'])
        if obj and obj.pk:
            readonly_fields.extend(['old_place', 'new_place'])
        return readonly_fields


@admin.register(Cell)
class CellAdmin(FiltersMixin, admin.ModelAdmin):
    search_fields = ['name']
    list_display = ['name', 'place']
    list_filter = (('place', RelatedAutocompleteFilter),)
    form = CellForm


@admin.register(Transmutation)
class TransmutationAdmin(FiltersMixin, admin.ModelAdmin):
    class Media:
        js = ('base/js/transmutation_source_item_autocomplete.js',)

    form = TransmutationForm
    list_display = [
        '__str__', 'created_at', 'completed_at', 'source',
    ]
    list_filter = [
        ('source', MPTTRelatedAutocompleteFilter),
        'is_completed',
    ]
    search_fields = ['source__name', 'transaction_items__category__name']
    inlines = [
        TransmutationItemInline
    ]

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_completed:
            return False
        else:
            return super(TransmutationAdmin, self).has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if obj and obj.is_completed:
            readonly_fields.extend(['source', 'destination', 'completed_at'])
        return readonly_fields

    def get_fields(self, request, obj=None):
        fields = super(TransmutationAdmin, self).get_fields(request, obj)
        if obj and obj.is_completed:
            fields.remove('force_complete')
        return fields

    def get_inline_instances(self, request, obj=None):
        inline_instances = []

        if obj and obj.transaction_ptr.is_completed:
            _inlines = [TransmutationItemInlineReadonly, ]
        else:
            _inlines = self.inlines
        self._obj = obj

        for inline_class in _inlines:
            inline = inline_class(self.model, self.admin_site)
            inline_instances.append(inline)
        return inline_instances

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance.save()
        formset.save_m2m()
        if self._obj:
            t = self._obj
            if hasattr(t, "is_pending") and t.is_pending:
                # print "complete pending transaction"
                t.is_pending = False
                t.transmute()


@admin.register(Warranty)
class WarrantyAdmin(FiltersMixin, admin.ModelAdmin):
    search_fields = ['serial__serial', 'serial__item__category__name']
    list_display = ['__str__', 'category_name', 'date']
    list_filter = [
        ('serial__item__category', MPTTRelatedAutocompleteFilter)
    ]
    form = WarrantyForm


@admin.register(Return)
class ReturnAdmin(FiltersMixin, admin.ModelAdmin):
    class Media:
        js = ('base/js/transmutation_source_item_autocomplete.js',)

    form = ReturnForm
    list_display = [
        '__str__', 'created_at', 'is_completed', 'completed_at', 'source', 'destination',
    ]
    list_filter = [
        ('source', MPTTRelatedAutocompleteFilter),
        'is_completed',
    ]
    search_fields = ['source__name', 'transaction_items__category__name']
    inlines = [
        ReturnItemInline
    ]

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_completed:
            return False
        else:
            return super(ReturnAdmin, self).has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if obj and obj.is_completed:
            readonly_fields.extend(['source', 'destination', 'completed_at'])
        return readonly_fields

    def get_fields(self, request, obj=None):
        fields = super(ReturnAdmin, self).get_fields(request, obj)
        if obj and obj.is_completed:
            fields.remove('force_complete')
        return fields

    def get_inline_instances(self, request, obj=None):
        inline_instances = []

        if obj and obj.transaction_ptr.is_completed:
            _inlines = [ReturnItemInlineReadonly, ]
        else:
            _inlines = self.inlines
        self._obj = obj

        for inline_class in _inlines:
            inline = inline_class(self.model, self.admin_site)
            inline_instances.append(inline)
        return inline_instances

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            instance.save()
        formset.save_m2m()
        if self._obj:
            t = self._obj
            if hasattr(t, "is_pending") and t.is_pending:
                # print "complete pending transaction"
                t.is_pending = False
                t.ret()
