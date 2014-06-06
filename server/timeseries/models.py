from django.db import models
import re
import datetime
import pytz

class TimeseriesBase(models.Model):
	'''The minimum structure of a timeseries model. Other time-logging models should inherit from this class.
	'''
	Time = models.DateTimeField(db_column='time')
	temporary = models.BooleanField(default=False) # whether or not this entry will be removed after a set time

	@classmethod
	def remove_expired(cls, timespan=datetime.timedelta(hours=24)):
		"""Remove all entries tagged with `temporary` and that are older than (now - timespan)
		"""
		now = pytz.UTC.localize(datetime.datetime.utcnow())
		earliest = now - timespan
		query = cls.objects.filter(Time__lt=earliest, temporary=True)
		query.delete() # this call immediately hits the database and removes all the entries in the queryset

	@classmethod
	def get_field_names(cls):
		"""Return all field names but none of the header names
		"""
		fields = []
		idx_col = cls.get_index_column()
		exclude = [u'id', u'temporary', u'Time', idx_col]
		if hasattr(cls, "_meta"):
			if hasattr(cls._meta, "fields"):
				fields = [field.get_attname() for field in cls._meta.fields if field.name not in exclude]
		return fields

	@classmethod
	def get_index_column(cls):
		"""Return the column names which are unique together (together they act as a unique identifier for a row)
		"""
		# unique_together is a tuple of tuples, e.g. (('Time', 'System'),)
		if hasattr(cls, "_meta"):
			if hasattr(cls._meta, "unique_together"):
				if len(cls._meta.unique_together) > 0:
					try:
						unq = list(cls._meta.unique_together[0])
						unq.remove('Time')
						return unq[0]
					except:
						pass
		return None

	@classmethod
	def latest(cls, temporary=None):
		"""return a datetime object that is the timestamp of the most recent entries in this table
		"""
		if temporary is None:
			return (cls.objects.order_by('-Time')[0]).Time
		else:
			return (cls.objects.filter(temporary=temporary).order_by('-Time')[0]).Time

	def index(self):
		"""return the index value of this object (or None if it has no index)
		"""
		col = self.get_index_column()
		if not col: return
		obj_dict = vars(self)
		return obj_dict[col]

	def index_tuple(self):
		"""return a tuple of (index id, index value) for this object (or None if no index)
		"""
		col = self.get_index_column()
		if not col: return
		# check if foreign-key index
		field = self._meta.get_field_by_name(col)[0]
		obj_dict = vars(self)
		if field.rel:
			# get object from foreign key table. django appends _id to foreign keys in the object's __dict__.
			foreign_key_id = obj_dict[col+'_id']
			foreign_key_object = field.related.parent_model.objects.get(id=foreign_key_id)
			return (foreign_key_object.id, str(foreign_key_object))
		else:
			# just get value out of self and stringify it
			index_object = obj_dict[col]
			return (index_object, str(index_object))

	@classmethod
	def get_latest_index_tuples(cls, queryset_latest=None):
		"""construct a list of tuples (id,name) for this model's index (or empty list if no index)
		"""
		# ideally the queryset is passed in so it can be reused. if not, here it is:
		if not queryset_latest:
			queryset_latest = cls.objects.filter(Time=cls.latest())
		# make a list by mapping the index_tuple function onto each object in the queryset
		return map(lambda obj: obj.index_tuple(), queryset_latest)

	class Meta:
		abstract = True

class ModelRegistry(models.Model):
	'''This table keeps track of registered timeseries models and related information'''

	# see timeseries.scrapers.ScraperBase.get_and_save_single
	# for an example of how these are used
	STATUS_CHOICES = (
		(2, 'Communication Error'),
		(1, 'Formatting Error'),
		(0, 'OK'))
	
	__regex_non_char = re.compile(r'[^a-zA-Z]+')

	system = models.CharField(max_length=16)
	short_name = models.CharField(max_length=32) # aka subsystem
	description = models.TextField()
	status = models.IntegerField(choices=STATUS_CHOICES) # latest status of this model's scraper
	model_class = models.CharField(max_length=64)
	scraper_class = models.CharField(max_length=64, null=True)

	def __unicode__(self):
		return unicode(self.short_name)

	def make_id(self):
		"""Convert the short_name into an HTML-usable id (no spaces or special characters)
		"""
		# a regualar expression to capture a sequence of non-letter characters
		words = ModelRegistry.__regex_non_char.split(self.short_name)
		caps = [w.capitalize() for w in words]
		return ''.join(caps)

	def schema(self):
		"""create a dictionary representation of this registry's model's schema (see timeseries.helpers.systems_schema)"""
		from timeseries import helpers as h
		model = h.get_registered_model(self.model_class)
		# break fields up into numeric and string types
		# (note that some types aren't covered in either numeric or string, like AutoField, ForeignKey, etc. since these are for data columns only)
		fields = model._meta.fields
		numeric_fields = filter(lambda f: f.get_internal_type() in h.model_types['numeric'], fields)
		string_fields  = filter(lambda f: f.get_internal_type() in h.model_types['string'] and f.attname != 'temporary', fields)
		schema = {
			'system' : self.system,
			'subsystem' : self.short_name,
			'indexes' : model.get_latest_index_tuples(),
			'id' : self.make_id(),
			'status' : self.status,
			'numeric' : h.field_name_tuples(numeric_fields, self),
			'string' : h.field_name_tuples(string_fields, self),
			'units' : {} # TODO
		}
		return schema