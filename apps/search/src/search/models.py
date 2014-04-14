#!/usr/bin/env python
# Licensed to Cloudera, Inc. under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  Cloudera, Inc. licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools
import json
import logging
import math
import re

from django.db import models
from django.utils.translation import ugettext as _, ugettext_lazy as _t
from django.core.urlresolvers import reverse

from search.api import SolrApi
from search.conf import SOLR_URL


LOG = logging.getLogger(__name__)


class Facet(models.Model):
  _ATTRIBUTES = ['properties', 'fields', 'ranges', 'dates', 'charts', 'order']

  enabled = models.BooleanField(default=True)
  data = models.TextField()

  def get_data(self):
    return json.loads(self.data)

  def update_from_post(self, post_data):
    data_dict = json.loads(self.data)

    for attr in Facet._ATTRIBUTES:
      if post_data.get(attr) is not None:
        data_dict[attr] = json.loads(post_data[attr])

    self.data = json.dumps(data_dict)


  def get_query_params(self):
    data_dict = json.loads(self.data)

    properties = data_dict.get('properties')

    params = (
      ('facet', properties.get('isEnabled') and 'true' or 'false'),
      ('facet.mincount', properties.get('mincount')),
      ('facet.limit', 100),
      ('facet.sort', properties.get('sort')),
    )

#    if data_dict.get('fields'):
#      field_facets = tuple([('facet.field', field_facet['field']) for field_facet in data_dict['fields']])
#      params += field_facets

    if data_dict.get('charts'):
      for field_facet in data_dict['charts']:
        if field_facet['start'] and field_facet['end'] and field_facet['gap']:
          range_facets = tuple([
             ('facet.range', field_facet['field']),
             ('f.%s.facet.limit' % field_facet['field'], -1),
             ('f.%s.facet.range.start' % field_facet['field'], field_facet['start']),
             ('f.%s.facet.range.end' % field_facet['field'], field_facet['end']),
             ('f.%s.facet.range.gap' % field_facet['field'], field_facet['gap']),]
          )
          params += range_facets
        else:
          field_facets = tuple([
            ('facet.field', field_facet['field']),
            ('f.%s.facet.limit' % field_facet['field'], -1),
          ])
          params += field_facets

    if data_dict.get('ranges'):
      for field_facet in data_dict['ranges']:
        range_facets = tuple([
           ('facet.range', field_facet['field']),
           ('f.%s.facet.range.start' % field_facet['field'], field_facet['start']),
           ('f.%s.facet.range.end' % field_facet['field'], field_facet['end']),
           ('f.%s.facet.range.gap' % field_facet['field'], field_facet['gap']),]
        )
        params += range_facets

    if data_dict.get('dates'):
      for field_facet in data_dict['dates']:
        start = field_facet['start']
        end = field_facet['end']
        gap = field_facet['gap']

        date_facets = tuple([
           ('facet.date', field_facet['field']),
           ('f.%s.facet.date.start' % field_facet['field'], 'NOW-%(frequency)s%(unit)s/%(rounder)s' % {"frequency": start["frequency"], "unit": start["unit"], "rounder": gap["unit"]}),
           ('f.%s.facet.date.end' % field_facet['field'], 'NOW-%(frequency)s%(unit)s' % end),
           ('f.%s.facet.date.gap' % field_facet['field'], '+%(frequency)s%(unit)s' % gap),]
        )
        params += date_facets

    return params


class Result(models.Model):
  _ATTRIBUTES = ['properties', 'template', 'highlighting', 'extracode']

  data = models.TextField()

  def update_from_post(self, post_data):
    data_dict = json.loads(self.data)

    for attr in Result._ATTRIBUTES:
      if post_data.get(attr) is not None:
        data_dict[attr] = json.loads(post_data[attr])

    self.data = json.dumps(data_dict)


  def get_template(self, with_highlighting=False):
    data_dict = json.loads(self.data)

    template = data_dict.get('template')
    if with_highlighting and data_dict.get('highlighting'):
      for field in data_dict.get('highlighting', []):
        template = re.sub('\{\{%s\}\}' % field, '{{{%s}}}' % field, template)

    return template

  def get_extracode(self):
    data_dict = json.loads(self.data)
    return data_dict.get('extracode')

  def get_highlighting(self):
    data_dict = json.loads(self.data)
    return json.dumps(data_dict.get('highlighting'))

  def get_properties(self):
    data_dict = json.loads(self.data)
    return json.dumps(data_dict.get('properties'))

  def get_query_params(self):
    data_dict = json.loads(self.data)

    params = ()

    if data_dict.get('highlighting'):
      params += (
        ('hl', data_dict.get('properties', {}).get('highlighting_enabled') and 'true' or 'false'),
        ('hl.fl', ','.join(data_dict.get('highlighting'))),
      )

    return params


class Sorting(models.Model):
  _ATTRIBUTES = ['properties', 'fields']

  data = models.TextField()

  def update_from_post(self, post_data):
    data_dict = json.loads(self.data)

    for attr in Sorting._ATTRIBUTES:
      if post_data.get(attr) is not None:
        data_dict[attr] = json.loads(post_data[attr])

    self.data = json.dumps(data_dict)


  def get_query_params(self, client_query=None):
    params = ()
    data_dict = json.loads(self.data)

    fields = []
    if data_dict.get('properties', {}).get('is_enabled') and 'true' or 'false':
      if client_query is not None and client_query.get('sort'):
        params += (
          ('sort', client_query.get('sort')),
        )
      elif data_dict.get('fields'):
        fields = []
        for field in data_dict.get('fields'):
          if field['include']:
            fields.append('%s %s' % (field['field'], field['asc'] and 'asc' or 'desc'))
        params += (
          ('sort', ','.join(fields)),
        )

    return params


class CollectionManager(models.Manager):

  def get_or_create(self, name, solr_properties, is_core_only=False, is_enabled=True, user=None):
    try:
      return self.get(name=name), False
    except Collection.DoesNotExist:
      facets = Facet.objects.create()
      result = Result.objects.create()      
      sorting = Sorting.objects.create()
      cores = json.dumps(solr_properties)

      collection = Collection.objects.create(
          name=name,
          label=name,
          enabled=is_enabled,
          cores=cores,
          is_core_only=is_core_only,
          facets=facets,
          result=result,
          sorting=sorting
      )

      collection.update_properties({'collection': collection.get_default(user)})
      collection.save()

      return collection, True      


class Collection(models.Model):
  enabled = models.BooleanField(default=True)
  name = models.CharField(max_length=40, verbose_name=_t('Solr index name pointing to'))
  label = models.CharField(max_length=100, verbose_name=_t('Friendlier name in UI'))
  is_core_only = models.BooleanField(default=False)
  cores = models.TextField(default=json.dumps({}), verbose_name=_t('Collection with cores data'), help_text=_t('Solr json'))
  properties = models.TextField(
      default=json.dumps({}), verbose_name=_t('Properties'),
      help_text=_t('Hue properties (e.g. results by pages number)')
  )

  facets = models.ForeignKey(Facet)
  result = models.ForeignKey(Result)
  sorting = models.ForeignKey(Sorting)

  _ATTRIBUTES = ['collection', 'layout', 'autocomplete']
  ICON = '/search/static/art/icon_search_24.png'

  objects = CollectionManager()

  def get_c(self, user):
    props = self.properties_dict

    if 'collection' not in props:
      props['collection'] = self.get_default(user)
    if 'layout' not in props:
      props['layout'] = []    

# to reset collection:
#    props['collection'] = self.get_default(user) # to reset
#    props['layout'] = []
    
    # Adding dynamic properties
    props['collection']['template']['extended_fields'] = self.fields_data(user)
   
    return json.dumps(props)

  def get_default(self, user):      
    extended_fields = self.fields_data(user)
    id_field = [field['name'] for field in extended_fields if field.get('isId')]
    if id_field:
      id_field = id_field[0]
    fields = [field.get('name') for field in self.fields_data(user)]
  
    TEMPLATE = {
      "extracode": "<style type=\"text/css\">\nem {\n  font-weight: bold;\n  background-color: yellow;\n}</style>", "highlighting": [""],
      "properties": {"highlighting_enabled": True},
      "template": """
      <div class="row-fluid">
        <div class="row-fluid">
          <div class="span12">%s</div>
        </div>
        <br/>
      </div>""" % ' '.join(['{{%s}}' % field for field in fields]), 
      "isGridLayout": True,
      "showFieldList": True,
      "fields": fields
    }
    
    FACETS = {
      "dates": [], "fields": [],
      "charts": [], "properties": {"sort": "count", "mincount": 1, "isEnabled": True, "limit": 10, 'schemd_id_field': 'id'}, "ranges": [], "order": []
    };  
    
    collection_properties = {
      'id': self.id, 'name': self.name, 'template': TEMPLATE, 'facets': FACETS['fields'], 
      'fields': fields, 'idField': id_field, 
    };      
    
    return collection_properties

  def get_absolute_url(self):
    return reverse('search:index') + '?collection=%s' % self.id

  def fields(self, user):
    return sorted([str(field.get('name', '')) for field in self.fields_data(user)])

  def fields_data(self, user):
    schema_fields = SolrApi(SOLR_URL.get(), user).fields(self.name)
    schema_fields = schema_fields['schema']['fields']

    return sorted([{'name': str(field), 'type': str(attributes.get('type', '')),
                    'isId': attributes.get('required') and attributes.get('uniqueKey')
                  }
                  for field, attributes in schema_fields.iteritems()])

  @property
  def properties_dict(self):
    if not self.properties:
      self.data = json.dumps({})
    properties_python = json.loads(self.properties)
    # Backward compatibility
    if 'autocomplete' not in properties_python:
      properties_python['autocomplete'] = False
    # TODO: Should convert old Hue 3.5 format here
    if 'collection' in properties_python:
      if 'showFieldList' not in properties_python['collection']['template']:
        properties_python['collection']['template']['showFieldList'] = True

    return properties_python

  def update_properties(self, post_data):
    prop_dict = self.properties_dict

    for attr in Collection._ATTRIBUTES:
      if post_data.get(attr) is not None:
        prop_dict[attr] = post_data[attr]

    self.properties = json.dumps(prop_dict)

  @property
  def autocomplete(self):
    return self.properties_dict['autocomplete']

  @autocomplete.setter
  def autocomplete(self, autocomplete):
    properties_ = self.properties_dict
    properties_['autocomplete'] = autocomplete
    self.properties = json.dumps(properties_)

  @property
  def icon(self):
    if self.name == 'twitter_demo':
      return '/search/static/art/icon_twitter.png'
    elif self.name == 'yelp_demo':
      return '/search/static/art/icon_yelp.png'
    elif self.name == 'log_demo':
      return '/search/static/art/icon_logs.png'
    else:
      return '/search/static/art/icon_search_24.png'

def get_facet_field_format(field, type, facets):
  format = ""
  try:
    if type == 'field':
      for fld in facets['fields']:
        if fld['field'] == field:
          format = fld['format']
    elif type == 'range':
      for fld in facets['ranges']:
        if fld['field'] == field:
          format = fld['format']
    elif type == 'date':
      for fld in facets['dates']:
        if fld['field'] == field:
          format = fld['format']
  except:
    pass
  return format

def get_facet_field(field, facets):
  facets = filter(lambda facet: facet['type'] == 'field' and facet['field'] == field, facets)
  if facets:
    return facets[0]
  else:
    return None

def get_facet_field_label(field, facets):
  label = field

  facets = filter(lambda facet: facet['type'] == 'field' and facet['field'] == field, facets)
  if facets:
    return facets[0]['label']
#  if type == 'field':
#    for fld in facets['fields']:
#      if fld['field'] == field:
#        label = fld['label']
#  elif type == 'range':
#    for fld in facets['ranges']:
#      if fld['field'] == field:
#        label = fld['label']
#  elif type == 'date':
#    for fld in facets['dates']:
#      if fld['field'] == field:
#        label = fld['label']
#  elif type == 'chart':
#    for fld in facets['charts']:
#      if fld['field'] == field:
#        label = fld['label']
  return label

def get_facet_field_uuid(field, type, facets):
  uuid = ''
  if type == 'field':
    for fld in facets['fields']:
      if fld['field'] == field:
        uuid = fld['uuid']
  elif type == 'range':
    for fld in facets['ranges']:
      if fld['field'] == field:
        uuid = fld['uuid']
  elif type == 'date':
    for fld in facets['dates']:
      if fld['field'] == field:
        uuid = fld['uuid']
  return uuid

def is_chart_field(field, charts):
  found = False
  for fld in charts:
    if field == fld['field']:
      found = True
  return found


def augment_solr_response2(response, collection, solr_query):
  augmented = response
  augmented['normalized_facets'] = []

  normalized_facets = []

  def pairwise2(cat, fq, iterable):
      pairs = []
      a, b = itertools.tee(iterable)
      for element in a:
        pairs.append({'cat': cat, 'value': element, 'count': next(a), 'selected': element == selected_field})
      return pairs

  fq = solr_query['fq']

  if response and response.get('facet_counts'):
    if response['facet_counts']['facet_fields']:
      for cat in response['facet_counts']['facet_fields']:
        selected_field = fq.get(cat, '')
        collection_facet = get_facet_field(cat, collection['facets'])
        facet = {
          'id': collection_facet['id'],
          'field': cat,
          'type': 'field',
          'label': get_facet_field_label(cat, collection['facets']),
          'counts': pairwise2(cat, selected_field, response['facet_counts']['facet_fields'][cat]),
        }
        normalized_facets.append(facet)

  # TODO HTML escape docs!
  
  highlighted_fields = response.get('highlighting', {}).keys()
  if highlighted_fields:
    id_field = collection.get('idField')    
    if id_field:
      for doc in response['response']['docs']:
        if id_field in doc and doc[id_field] in highlighted_fields:
          doc.update(response['highlighting'][doc[id_field]])
    else:
      response['warning'] = _("The Solr schema requires an id field for performing the result highlighting")
      
        
  response['total_pages'] = int(math.ceil((float(response['response']['numFound']) / float(solr_query['rows']))))
  response['search_time'] = response['responseHeader']['QTime']

  if normalized_facets:
    augmented['normalized_facets'].extend(normalized_facets)

  return augmented

def augment_solr_exception(response, collection, solr_query):
  response.update(
  {
    "facet_counts": {   
    },
    "highlighting": {
    },
    "normalized_facets": [
      {
        "field": facet['field'],
        "counts": [],
        "type": facet['type'],
        "label": facet['label']
      }
      for facet in collection['facets']
    ],
    "responseHeader": {
      "status": -1,
      "QTime": 0,
      "params": {
      }
    },
    "response": {
      "start": 0,
      "numFound": 0,
      "docs": [
      ]
    }
  }) 

def augment_solr_response(response, facets, solr_query):
  augmented = response
  augmented['normalized_facets'] = []

  normalized_facets = {}
  default_facets = []

  chart_facets = facets.get('charts', [])

  def pairwise(iterable):
      "s -> (s0,s1), (s1,s2), (s2, s3), ..."
      a, b = itertools.tee(iterable)
      next(b, None)
      return list(itertools.izip(a, b))

  def pairwise2(cat, fq, iterable):
      pairs = []
      a, b = itertools.tee(iterable)
      for element in a:
        pairs.append({'cat': cat, 'value': element, 'count': next(a), 'selected': element == selected_field})
      return pairs

  fq = solr_query['fq']

  if response and response.get('facet_counts'):
    if response['facet_counts']['facet_fields']:
      for cat in response['facet_counts']['facet_fields']:
        selected_field = fq.get(cat, '')
        facet = {
          'field': cat,
          'type': 'chart' if is_chart_field(cat, chart_facets) else 'field',
          'label': get_facet_field_label(cat, is_chart_field(cat, chart_facets) and 'chart' or 'field', facets),
          'counts': pairwise2(cat, selected_field, response['facet_counts']['facet_fields'][cat]),
        }
        uuid = get_facet_field_uuid(cat, 'field', facets)
        if uuid == '':
          default_facets.append(facet)
        else:
          normalized_facets[uuid] = facet

    if response['facet_counts']['facet_ranges']:
      for cat in response['facet_counts']['facet_ranges']:
        facet = {
          'field': cat,
          'type': 'chart' if is_chart_field(cat, chart_facets) else 'range',
          'label': get_facet_field_label(cat, 'range', facets),
          'counts': response['facet_counts']['facet_ranges'][cat]['counts'],
          'start': response['facet_counts']['facet_ranges'][cat]['start'],
          'end': response['facet_counts']['facet_ranges'][cat]['end'],
          'gap': response['facet_counts']['facet_ranges'][cat]['gap'],
        }
        uuid = get_facet_field_uuid(cat, 'range', facets)
        if uuid == '':
          default_facets.append(facet)
        else:
          normalized_facets[uuid] = facet

    if response['facet_counts']['facet_dates']:
      for cat in response['facet_counts']['facet_dates']:
        facet = {
          'field': cat,
          'type': 'date',
          'label': get_facet_field_label(cat, 'date', facets),
          'format': get_facet_field_format(cat, 'date', facets),
          'start': response['facet_counts']['facet_dates'][cat]['start'],
          'end': response['facet_counts']['facet_dates'][cat]['end'],
          'gap': response['facet_counts']['facet_dates'][cat]['gap'],
        }
        counts = []
        for date, count in response['facet_counts']['facet_dates'][cat].iteritems():
          if date not in ('start', 'end', 'gap'):
            counts.append(date)
            counts.append(count)
        facet['counts'] = counts

        uuid = get_facet_field_uuid(cat, 'date', facets)
        if uuid == '':
          default_facets.append(facet)
        else:
          normalized_facets[uuid] = facet

  for ordered_uuid in facets.get('order', []):
    try:
      augmented['normalized_facets'].append(normalized_facets[ordered_uuid])
    except:
      pass
  if default_facets:
    augmented['normalized_facets'].extend(default_facets)

  return augmented
