# -*- encoding: utf-8 -*-
from calendar import Calendar
from typing import Tuple, Iterable, Dict, List

from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import models
from django.db.models.signals import m2m_changed
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _
from datetime import date, datetime
from colorfield.fields import ColorField
import pytz

Date = str  # "%Y-%m-%d" format, i.e. "2016-01-01"
Day = str  # "%2d" format, i.e. "01", "02", "15"
Weekday = str  # "sun", "mon", "tue" ...
tz = pytz.timezone(settings.TIME_ZONE)


class Person(models.Model):
    """
    People with their full names in this model
    """
    last_name = models.CharField(_("last name"), max_length=64)
    first_name = models.CharField(_("first name"), max_length=64)
    middle_name = models.CharField(_("middle name"), max_length=64)
    vacation_scheme = models.ForeignKey("VacationScheme", verbose_name=_("vacation scheme"))

    class Meta:
        verbose_name = _('person')
        verbose_name_plural = _('persons')
        ordering = ('last_name', 'first_name')

    def __str__(self) -> str:
        return self.get_short_name()

    def get_short_name(self) -> str:
        """
        :return: string with users's last name and initials.
        """
        return "{last_name} {first_name}. {middle_name}.".format(
                last_name=self.last_name.capitalize(),
                first_name=self.first_name[0].upper() if self.first_name else '?',
                middle_name=self.middle_name[0].upper() if self.middle_name else '?'
        )

    def get_full_name(self) -> str:
        """
        :return: string with users's full name.
        """
        return "{last_name} {first_name} {middle_name}".format(
                last_name=self.last_name.capitalize(),
                first_name=self.first_name.capitalize(),
                middle_name=self.middle_name.capitalize()
        )


MON = 0
TUE = 1
WED = 2
THU = 3
FRI = 4
SAT = 5
SUN = 6

WEEKDAYS = {
    MON: 'mon',
    TUE: 'tue',
    WED: 'wed',
    THU: 'thu',
    FRI: 'fri',
    SAT: 'sat',
    SUN: 'sun',
}


class YearlyCalendarScheme(models.Model):
    """
    This scheme contains information about working days and holidays in year.
    This data is used in calculation of working days and hours each month.
    Overrides data in :class:`.WeeklyCalendarScheme`

    .. note:: Working days with different hours values are considered to be equal for SALARY_TYPE_DAILY
              and SALARY_TYPE_DAILY_MB
    """
    name = models.CharField(_("weekly calendar scheme name"), max_length=100, unique=True)

    class Meta:
        verbose_name = _('yearly calendar scheme')
        verbose_name_plural = _('yearly calendar schemes')

    def __str__(self):
        return self.name


class YearlyCalendarSchemeRow(models.Model):
    """
    Data for :class:`YearlyCalendarScheme`
    Zero value is considered as a day off.
    """
    scheme = models.ForeignKey(YearlyCalendarScheme, related_name="rows", verbose_name=_("yearly calendar scheme"))
    date = models.DateField(_("date"), db_index=True)
    hours = models.PositiveSmallIntegerField(_("hours"), default=0)
    description = models.CharField(_("description"), max_length=64, blank=True, null=True)

    class Meta:
        verbose_name = _('yearly calendar scheme row')
        verbose_name_plural = _('yearly calendar schemes rows')

    def __str__(self):
        return self.description or self.date.strftime("%Y-%m-%d")


class WeeklyCalendarScheme(models.Model):
    """
    This scheme contains information about working days in week.
    Working hours for each week day should be specified in corresponding fields.
    Zero value is considered as a day off.
    This data is used in calculation of working days and hours each month
    and may be overridden in :class:`.YearlyCalendarScheme`

    .. note:: Working days with different hours values are considered to be equal for SALARY_TYPE_DAILY
              and SALARY_TYPE_DAILY_MB
    """
    name = models.CharField(_("weekly calendar scheme name"), max_length=100, unique=True)
    mon = models.PositiveSmallIntegerField(_("monday hours"), default=0)
    tue = models.PositiveSmallIntegerField(_("tuesday hours"), default=0)
    wed = models.PositiveSmallIntegerField(_("wednesday hours"), default=0)
    thu = models.PositiveSmallIntegerField(_("thursday hours"), default=0)
    fri = models.PositiveSmallIntegerField(_("friday hours"), default=0)
    sat = models.PositiveSmallIntegerField(_("saturday hours"), default=0)
    sun = models.PositiveSmallIntegerField(_("sunday hours"), default=0)

    class Meta:
        verbose_name = _('weekly calendar scheme')
        verbose_name_plural = _('weekly calendar schemes')

    def __str__(self):
        return self.name


class CalendarScheme(models.Model):
    """
    This scheme contains information about working days.
    """
    name = models.CharField(_("calendar scheme name"), max_length=100, unique=True)
    weekly_calendar_scheme = models.ForeignKey(WeeklyCalendarScheme, verbose_name=_("weekly calendar scheme"))
    yearly_calendar_scheme = models.ForeignKey(YearlyCalendarScheme, verbose_name=_("yearly calendar scheme"))
    default_scheme = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('calendar scheme')
        verbose_name_plural = _('calendar schemes')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """
        Only one default scheme may be at once.
        So if current instance has default_scheme=True, update others and set default=False
        :param args:
        :param kwargs:
        :return: CalendarScheme instance
        """
        if self.default_scheme:
            CalendarScheme.objects.all().update(default_scheme=False)
        super(CalendarScheme, self).save(*args, **kwargs)

    @staticmethod
    def _get_month_days(year: int, month: int) -> List[Tuple[Date, Weekday, Day]]:
        """
        :param year:
        :type year: integer
        :param month:
        :type month: integer
        :returns: list of tuples (date, weekday) i.e. ("2016-01-01", "fri") for all days of given month
        :rtype: List[Tuple[Date, Weekday, Day]]
        """
        cal = Calendar()
        result = []  # type: List[Tuple[Date, Weekday, Day]]
        for day, weekday in cal.itermonthdays2(year, month):
            if day:
                result.append(("{year}-{month}-{day}".format(
                        year=str(year),
                        month=str(month).zfill(2),
                        day=str(day).zfill(2)
                ), WEEKDAYS[weekday], str(day).zfill(2)))
        return result

    def _get_month_working_hours(self, year: int, month: int) -> Dict[Date, int]:
        """
        :param year:
        :type year: integer
        :param month:
        :type month: integer
        :returns: dictionary, keys are all days of the months in "%Y-%m-%d" format, values - working hours for this day.
        :rtype: Dict[Date, int]:
        """
        wcs = self.weekly_calendar_scheme  # type: WeeklyCalendarScheme
        ycs = self.yearly_calendar_scheme  # type: YearlyCalendarScheme
        result = {}  # type: Dict[Date, int]
        month_dates = self._get_month_days(year, month)  # type: List[Tuple[Date, Weekday, Day]]
        month_start = month_dates[0][0]
        month_end = month_dates[-1][0]

        for dt, weekday, day in month_dates:
            result.update({
                dt: getattr(wcs, weekday, 0)
            })

        for row in ycs.rows.filter(models.Q(date__gte=month_start) & models.Q(date__lte=month_end)):
            day = row.date.strftime("%Y-%m-%d")
            result.update({
                day: row.hours
            })

        return result

    def get_month_working_hours(self, year: int, month: int) -> Dict[Date, int]:
        return self._get_month_working_hours(year, month)

    def get_month_working_days(self, year: int, month: int) -> List[Dict]:
        """

        :param year:
        :type year: integer
        :param month:
        :type month: integer
        :return:
        """
        wh = self._get_month_working_hours(year, month)
        md = self._get_month_days(year, month)

        result = []  # type: List[Dict]
        dt_today = date.today().strftime("%Y-%m-%d")

        for dt, weekday, day in md:
            result.append({
                'dt': dt,
                'day': day,
                'weekday': _(weekday),
                'hours': wh[dt],
                'eow': weekday == 'sun',
                'cur': dt == dt_today
            })

        return result

    def get_working_days_count(self, year: int, month: int) -> int:
        """
        :param year:
        :type year: integer
        :param month:
        :type month: integer
        :return: number of working days in month according current calendar scheme
        :rtype: integer
        """
        wh = self._get_month_working_hours(year, month)  # type: Dict[Date, int]
        return len(list(filter(lambda date: wh[date], wh)))

    def get_working_hours_count(self, year: int, month: int) -> int:
        """
        :param year:
        :type year: integer
        :param month:
        :type month: integer
        :return: number of working hours in month according current calendar scheme
        :rtype: integer
        """
        wh = self._get_month_working_hours(year, month)  # type: Dict[Date, int]
        return sum(wh.values())


class Role(models.Model):
    """
    Model which represents all possible workers roles with salaries and working calendar dependencies.
    """

    # TODO: Role can be changed, but we need consistent history.
    # TODO possible solution: Clone Role data, new object after edit, old object in history.

    SALARY_TYPE_HOURLY = 1
    SALARY_TYPE_HOURLY_MB = 2
    SALARY_TYPE_DAILY = 3
    SALARY_TYPE_DAILY_MB = 4

    SALARY_TYPES = (
        (SALARY_TYPE_HOURLY, _('hourly salary')),
        (SALARY_TYPE_HOURLY_MB, _('hourly salary, month based')),
        (SALARY_TYPE_DAILY, _('daily salary')),
        (SALARY_TYPE_DAILY_MB, _('daily salary, month based')),

    )

    name = models.CharField(_("role name"), max_length=100, unique=True)
    salary_type = models.PositiveSmallIntegerField(_("salary type"), choices=SALARY_TYPES)
    salary = models.DecimalField(_('salary value'), max_digits=10, decimal_places=2, default=0.0,
                                 help_text=_("If salary type is monthly based, salary value should be equal to month \
                                 reward. Otherwise hourly or daily reward"))
    # day_off_multiplier = models.DecimalField(_("day off multiplier"), max_digits=5, decimal_places=3, default=1.0)
    # overtime_multiplier = models.DecimalField(_("overtime multiplier"), max_digits=5, decimal_places=3, default=1.0)
    calendar_scheme = models.ForeignKey("CalendarScheme", verbose_name=_("calendar scheme"))
    color = ColorField(blank=True, null=True)
    is_paid_on_vacation = models.BooleanField(_("is paid on vacation"), default=False)
    date_start = models.DateTimeField(_("start date"), default=timezone.now)
    date_end = models.DateTimeField(_("end date"), blank=True, null=True)
    replaced_by = models.ForeignKey("Role", blank=True, null=True)

    class Meta:
        verbose_name = _('role')
        verbose_name_plural = _('roles')
        ordering = ['-replaced_by__id', 'name']

    def __str__(self):
        return self.name

    def clean(self):
        if self.date_end and self.date_end <= self.date_start:
            raise ValidationError({
                'date_end': _("date end must be greater than date start")
            })
        if self.pk:
            logs = WorkLog.objects.filter(role=self)
            if logs.count():
                old_pk = self.pk
                try:
                    old_ins = Role.objects.get(pk = old_pk)
                except Role.DoesNotExist:
                    pass
                else:
                    if(
                        not self.salary_type == old_ins.salary_type or
                        not self.salary == old_ins.salary or
                        not self.calendar_scheme == old_ins.calendar_scheme
                    ):
                        if self.date_start <= old_ins.date_start:
                            raise ValidationError({
                                'date_start': _("date start must be newer than in previous role version")
                            })
                        old_ins.name = "[%s] %s" % (self.date_start, self.name)
                        super(Role, old_ins).save()
                        self.pk = None
                        self.date_end = None
                        super(Role, self).save()
                        old_ins.replace_by(self, self.date_start)
        super(Role, self).clean()

    def full_clean(self, *args, **kwargs):
        return self.clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super(Role, self).save(*args, **kwargs)

    def replace_by(self, other_role, dt):
        self.date_end = dt
        self.replaced_by = other_role
        self.save()
        Role.objects.filter(replaced_by=self).update(replaced_by=other_role)
        for position in Position.objects.filter(roles__id=self.id):
            position.roles.remove(self)
            position.roles.add(other_role)
            logs = PositionRolesLog.objects.filter(
                    position=position, role_id=self, date_end__isnull=False
            ).order_by('-date_end')
            if logs.count():
                log = logs[0]
                log.date_end = dt
                log.save()
            try:
                log = PositionRolesLog.objects.get(position=position, role_id=other_role, date_end__isnull=True)
            except PositionRolesLog.DoesNotExist:
                pass
            else:
                log.date_start = dt
                log.save()
        WorkLog.objects.filter(role=self, date__gte=dt).update(role=other_role)


# class RoleGroup(models.Model):
#     """
#     Roles in role groups may be played by worker simultaneously. Nevertheless roles will be represented
#     separately in work log, but role groups will simplify API and user's interface.
#     """
#     name = models.CharField(_("role group name"), max_length=100, unique=True)
#     roles = models.ManyToManyField(Role, verbose_name=_("roles"))
#
#     class Meta:
#         verbose_name = _('role group')
#         verbose_name_plural = _('role groups')
#
#     def __str__(self):
#         return self.name


class Position(models.Model):
    """
    Worker position
    """
    name = models.CharField(_("position name"), max_length=100, unique=True)
    # role_groups = models.ManyToManyField(RoleGroup, verbose_name=_("role groups"), blank=True)
    roles = models.ManyToManyField(Role, verbose_name=_("roles"), blank=True)

    class Meta:
        verbose_name = _('position')
        verbose_name_plural = _('positions')

    def __str__(self):
        return self.name


class PositionRolesLog(models.Model):
    """
    Position roles changes are logged here
    """
    position = models.ForeignKey(Position, verbose_name=_("position"), related_name="role_logs")
    date_start = models.DateTimeField(_("start date"), default=timezone.now)
    date_end = models.DateTimeField(_("end date"), blank=True, null=True)
    role = models.ForeignKey(Role, verbose_name=_("role"), related_name="role_logs")

    class Meta:
        verbose_name = _('position role log')
        verbose_name_plural = _('positions roles logs')

    def __str__(self):
        return self.position.name


def roles_changed(instance, action, pk_set, **kwargs):
    if action == "post_clear":
        PositionRolesLog.objects.filter(position=instance, date_end__isnull=True).update(date_end=timezone.now())
    if action == "post_add":
        for pk in pk_set:
            PositionRolesLog.objects.get_or_create(position=instance, role_id=pk, date_start=timezone.now())
    if action == "post_remove":
        for pk in pk_set:
            try:
                log = PositionRolesLog.objects.get(position=instance, role_id=pk, date_end__isnull=True)
            except PositionRolesLog.DoesNotExist:
                log = PositionRolesLog.objects.create(position=instance, role_id=pk,
                                                      date_start=datetime(2016, 1, 1).replace(tzinfo=tz))
            log.date_end = timezone.now()
            log.save()

m2m_changed.connect(roles_changed, sender=Position.roles.through)


class Worker(models.Model):
    """
    User on Position = Worker.
    If date_end is not set or set in future - worker still active.
    If date_end is set in past - worker is resigned.
    """
    person = models.ForeignKey(Person, verbose_name=_("user"), related_name='workers')
    position = models.ForeignKey(Position, verbose_name=_("position"))
    date_start = models.DateTimeField(_("start date"), default=timezone.now)
    date_end = models.DateTimeField(_("end date"), blank=True, null=True)

    class Meta:
        verbose_name = _('worker')
        verbose_name_plural = _('workers')
        unique_together = ('person', 'position', 'date_end')

    def __str__(self):
        return "%s [%s]" % (self.person.get_short_name(), self.position.name)

    def is_active(self) -> bool:
        """
        :return: flag which shows if worker is still active
        :rtype: boolean
        """
        if not self.date_end or self.date_end < timezone.now():
            return True
        return False

    def get_roles(self) -> models.query.QuerySet:
        return self.position.roles.all()


class WorkLog(models.Model):
    """
    This model contains data about workers' spent hours. Each role has own record, no role groups here!
    """
    worker = models.ForeignKey(Worker, verbose_name=_("worker"), related_name='work_logs')
    role = models.ForeignKey(Role, verbose_name=_("role"), related_name='work_logs')
    date = models.DateField(_("date"))
    hours = models.DecimalField(_("hours"), max_digits=4, decimal_places=2)
    # is_day_off = models.BooleanField(_("is day off"), default=False)

    class Meta:
        verbose_name = _('work log')
        verbose_name_plural = _('work logs')
        unique_together = ('worker', 'role', 'date')

    def __str__(self):
        return "%s: %s" % (self.date.strftime("%Y-%m-%d"), self.hours)

    def save(self, *args, **kwargs):
        if self.hours == 0:
            if self.pk:
                self.delete()
        else:
            super(WorkLog, self).save(*args, **kwargs)


MODIFIER_TYPE_PLAIN = 1
MODIFIER_TYPE_MULTIPLIER = 2

MODIFIER_TYPES = (
    (MODIFIER_TYPE_PLAIN, _('plain modifier')),
    (MODIFIER_TYPE_MULTIPLIER, _('multiplier')),
)


class RegularModifier(models.Model):
    """
    Model with regular bounties or penalties.
    Monthly salary is calculated in such order:

    1. Wage is calculated for each role according to :class:`.WorkLog` entries
    2. Results are summed in total for each worker
    3. Regular modifiers applied to this total in order from lower priority to higher
    """
    worker = models.ForeignKey(Worker, verbose_name=_("worker"), related_name="regular_modifiers")  # type: Worker
    modifier_type = models.PositiveSmallIntegerField(_("modifier type"), choices=MODIFIER_TYPES,
                                                     default=MODIFIER_TYPE_PLAIN)
    value = models.DecimalField(_("modifier value"), max_digits=9, decimal_places=3)
    priority = models.PositiveSmallIntegerField(_("priority"), default=1)
    description = models.TextField(_("description"), blank=True, null=True)

    class Meta:
        verbose_name = _('regular modifier')
        verbose_name_plural = _('regular modifiers')
        unique_together = (
            ('worker', 'priority')
        )
        ordering = ('worker', 'priority')

    def __str__(self):
        if self.modifier_type == MODIFIER_TYPE_PLAIN:
            return "%s: %s" % (self.worker.person.get_short_name(), self.value if self.value < 0 else "+%s" % self.value)
        else:
            return "%s: *%s" % (self.worker.person.get_short_name(), self.value)


class Correction(models.Model):
    """
    Model with non-repeating bounties or penalties.
    Corrections applied after all :class:`.RegularModifier` ordered by timestamp field
    """
    worker = models.ForeignKey(Worker, verbose_name=_("worker"), related_name='corrections')  # type: Worker
    modifier_type = models.PositiveSmallIntegerField(_("correction type"), choices=MODIFIER_TYPES,
                                                     default=MODIFIER_TYPE_PLAIN)
    value = models.DecimalField(_("correction value"), max_digits=9, decimal_places=3)
    timestamp = models.DateTimeField(_("correction time"), default=timezone.now)
    description = models.TextField(_("description"), blank=True, null=True)

    class Meta:
        verbose_name = _('correction')
        verbose_name_plural = _('corrections')
        unique_together = (
            ('worker', 'timestamp')
        )
        ordering = ('timestamp', )

    def __str__(self):
        if self.modifier_type == MODIFIER_TYPE_PLAIN:
            return "%s: %s" % (self.worker.person.get_short_name(), self.value if self.value < 0 else "+%s" % self.value)
        else:
            return "%s: *%s" % (self.worker.person.get_short_name(), self.value)


class VacationType(models.Model):
    """
    Payout and salary percentage options for vacations are set in this model
    """
    name = models.CharField(_("vacation type"), max_length=100, unique=True)
    is_sick_leave = models.BooleanField(_("is sick leave?"), default=False)
    salary_percentage = models.DecimalField(_("salary percentage"), max_digits=3, decimal_places=2)
    payout_percentage = models.DecimalField(_("payout percentage"), max_digits=3, decimal_places=2)

    class Meta:
        verbose_name = _('vacation type')
        verbose_name_plural = _('vacation types')
        ordering = ('name', )

    def __str__(self):
        return self.name


class VacationScheme(models.Model):
    """
    Vacations and sick leaves setup. Data provided via m2m relations with :class:`.VacationType`
    """
    name = models.CharField(_("vacation scheme"), max_length=100, unique=True)

    class Meta:
        verbose_name = _('vacation scheme')
        verbose_name_plural = _('vacation schemes')
        ordering = ('name', )

    def __str__(self):
        return self.name


class VacationSchemeRow(models.Model):
    """
    m2m relations between :class:`.VacationType` and :class:`.VacationScheme`
    """
    vacation_scheme = models.ForeignKey(VacationScheme, verbose_name=_("vacation scheme"), related_name='rows')
    vacation_type = models.ForeignKey(VacationType, verbose_name=_("vacation type"))
    count = models.IntegerField(_("hours amount"))

    class Meta:
        verbose_name = _('vacation scheme row')
        verbose_name_plural = _('vacation scheme rows')

    def __str__(self):
        return "%s - %s" % (self.vacation_scheme.name, self.vacation_type.name)


class VacationLog(models.Model):
    """
    This model contains data about vacations and sick leaves.
    """
    person = models.ForeignKey(Person, verbose_name=_("person"), related_name='vacations')
    date = models.DateField(_("date"))
    hours = models.DecimalField(_("hours"), max_digits=4, decimal_places=2)
    is_sick_leave = models.BooleanField(_("is sick leave"), default=False)

    class Meta:
        verbose_name = _('vacation log')
        verbose_name_plural = _('vacation logs')
        unique_together = ('person', 'date', 'is_sick_leave')

    def __str__(self):
        return "%s: %s" % (self.date.strftime("%Y-%m-%d"), self.hours)

    def save(self, *args, **kwargs):
        if self.hours == 0:
            if self.pk:
                self.delete()
        else:
            super(VacationLog, self).save(*args, **kwargs)


class WorkLogMigration(models.Model):
    old_worker = models.ForeignKey(Worker, verbose_name=_("old worker"), related_name="old_workers")
    new_worker = models.ForeignKey(Worker, verbose_name=_("new worker"), related_name="new_workers")
    date_migrate_from = models.DateField(_("date migrate from"))
    commit = models.BooleanField(_("commit"), default=False)

    class Meta:
        verbose_name = _('work log migration')
        verbose_name_plural = _('work logs migrations')

    def __str__(self):
        return "%s: %s - %s" % (self.date_migrate_from.strftime("%Y-%m-%d"), self.old_worker, self.new_worker)

    def clean(self):
        if self.commit:
            if not self.pk:
                raise ValidationError({"commit":_("you have to save migration without commit first")})
            try:
                migration = WorkLogMigration.objects.get(pk=self.pk)
            except WorkLogMigration.DoesNotExist:
                raise ValidationError(_("something wrong with the migration"))
            else:
                if migration.commit:
                    raise ValidationError({"commit": _("you can not change committed migrations!")})
                else:
                    for role_migration in migration.role_migrations.all():
                        WorkLog.objects.filter(
                                worker=self.old_worker,
                                role=role_migration.old_role,
                                date__gte=self.date_migrate_from
                        ).update(
                            worker=self.new_worker,
                            role=role_migration.new_role,
                        )
                    if not self.old_worker == self.new_worker:
                        WorkLog.objects.filter(
                                worker=self.old_worker,
                                date__gte=self.date_migrate_from
                        ).delete()

    def full_clean(self, *args, **kwargs):
        return self.clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super(WorkLogMigration, self).save(*args, **kwargs)


class WorkLogRoleMigration(models.Model):
    migration = models.ForeignKey(WorkLogMigration, verbose_name=_("work log migration"), related_name="role_migrations")
    old_role = models.ForeignKey(Role, verbose_name=_("old role"), related_name="old_roles")
    new_role = models.ForeignKey(Role, verbose_name=_("new role"), blank=True, null=True, related_name="new_roles")

    class Meta:
        verbose_name = _('work log role migration')
        verbose_name_plural = _('work log roles migrations')
        unique_together = (
            ('migration', 'old_role', 'new_role')
        )

    def __str__(self):
        return "%s: %s - %s" % (self.migration.date_migrate_from.strftime("%Y-%m-%d"), self.old_role, self.new_role)

    def clean(self):
        if self.old_role not in self.migration.old_worker.get_roles():
            raise ValidationError(_("old role choice is invalid"))
        if self.new_role not in self.migration.new_worker.get_roles():
            raise ValidationError(_("new role choice is invalid"))

    def full_clean(self, *args, **kwargs):
        return self.clean()

    def save(self, *args, **kwargs):
        self.full_clean()
        super(WorkLogRoleMigration, self).save(*args, **kwargs)


