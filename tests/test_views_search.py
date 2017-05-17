# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2015, 2016 CERN.
#
# Invenio is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

"""Search tests."""

from __future__ import absolute_import, print_function

import re

import pytest
from flask import url_for
from helpers import assert_hits_len, get_json, parse_url, to_relative_url


def test_json_result_serializer(app, indexed_records, test_records,
                                search_url):
    """JSON result."""
    with app.test_client() as client:
        # Get a query with only one record
        res = client.get(search_url, query_string={'q': 'year:2015'})
        assert_hits_len(res, 1)
        assert res.status_code == 200

        # Check serialization of record
        record = get_json(res)['hits']['hits'][0]

        for k in ['id', 'created', 'updated', 'metadata', 'links']:
            assert k in record

        pid, db_record = test_records[0]
        assert record['id'] == int(pid.pid_value)
        assert record['metadata'] == db_record.dumps()


def test_page_size(app, indexed_records, search_url):
    """Test page and size parameters."""
    with app.test_client() as client:
        # Limit records
        res = client.get(search_url, query_string=dict(page=1, size=2))
        assert_hits_len(res, 2)

        # All records
        res = client.get(search_url, query_string=dict(page=1, size=10))
        assert_hits_len(res, len(indexed_records))

        # Exceed max result window
        res = client.get(search_url, query_string=dict(page=100, size=100))
        assert res.status_code == 400
        assert 'message' in get_json(res)


def test_pagination(app, indexed_records, search_url):
    """Test pagination."""
    with app.test_client() as client:
        # Limit records
        res = client.get(search_url, query_string=dict(size=1, page=1))
        assert_hits_len(res, 1)
        data = get_json(res)
        assert 'self' in data['links']
        assert 'next' in data['links']
        assert 'prev' not in data['links']

        # Assert next URL before calling it
        next_url = get_json(res)['links']['next']
        parsed_url = parse_url(next_url)
        assert parsed_url['qs']['size'] == ['1']
        assert parsed_url['qs']['page'] == ['2']

        # Access next URL
        res = client.get(to_relative_url(next_url))
        assert_hits_len(res, 1)
        data = get_json(res)
        assert data['links']['self'] == next_url
        assert 'next' in data['links']
        assert 'prev' in data['links']


def test_page_links(app, indexed_records, search_url):
    """Test Link HTTP header on multi-page searches."""
    with app.test_client() as client:
        # Limit records
        res = client.get(search_url, query_string=dict(size=1, page=1))
        assert_hits_len(res, 1)

        def parse_link_header(response):
            """Parses the links from a REST response's HTTP header."""
            return {
                k: v for (k, v) in
                map(lambda s: re.findall(r'<(.*)>; rel="(.*)"', s)[0][::-1],
                    [x for x in res.headers['Link'].split(', ')])
            }

        links = parse_link_header(res)
        data = get_json(res)['links']
        assert 'self' in data \
               and 'self' in links \
               and data['self'] == links['self']
        assert 'next' in data \
               and 'next' in links \
               and data['next'] == links['next']
        assert 'prev' not in data \
               and 'prev' not in links

        # Assert next URL before calling it
        first_url = links['self']
        next_url = links['next']
        parsed_url = parse_url(next_url)
        assert parsed_url['qs']['size'] == ['1']
        assert parsed_url['qs']['page'] == ['2']

        # Access next URL
        res = client.get(to_relative_url(next_url))
        assert_hits_len(res, 1)
        links = parse_link_header(res)
        assert links['self'] == next_url
        assert 'next' in links
        assert 'prev' in links and links['prev'] == first_url


def test_query(app, indexed_records, search_url):
    """Test query."""
    with app.test_client() as client:
        # Valid query syntax
        res = client.get(search_url, query_string=dict(q='back'))
        assert len(get_json(res)['hits']['hits']) == 2


@pytest.mark.parametrize('app', [dict(
    endpoint=dict(
        search_factory_imp='invenio_records_rest.query.es_search_factory'
    )
)], indirect=['app'])
def test_es_query_syntax(app, indexed_records, search_url):
    """Test ES query syntax."""
    with app.test_client() as client:
        # Valid ES query syntax
        res = client.get(search_url, query_string=dict(q='+title:back'))
        assert len(get_json(res)['hits']['hits']) == 2


def test_sort(app, indexed_records, search_url):
    """Test invalid accept header."""
    with app.test_client() as client:
        res = client.get(search_url, query_string={'sort': '-year'})
        assert res.status_code == 200
        # Min year in test records set.
        assert get_json(res)['hits']['hits'][0]['metadata']['year'] == 4242

        res = client.get(search_url, query_string={'sort': 'year'})
        assert res.status_code == 200
        # Max year in test records set.
        assert get_json(res)['hits']['hits'][0]['metadata']['year'] == 1985


def test_invalid_accept(app, indexed_records, search_url):
    """Test invalid accept header."""
    headers = [('Accept', 'application/does_not_exist')]

    with app.test_client() as client:
        res = client.get(search_url, headers=headers)
        assert res.status_code == 406
        data = get_json(res)
        assert 'message' in data
        assert data['status'] == 406


def test_aggregations_info(app, indexed_records, search_url):
    """Test aggregations."""
    with app.test_client() as client:
        # Facets are defined in the "app" fixture.
        res = client.get(search_url)
        data = get_json(res)
        assert 'aggregations' in data
        # len 3 because testrecords.json have three diff values for "stars"
        assert len(data['aggregations']['stars']['buckets']) == 3
        assert data['aggregations']['stars']['buckets'][0] == dict(
            key=4, doc_count=2
        )


def test_filters(app, indexed_records, search_url):
    """Test aggregations."""
    with app.test_client() as client:
        res = client.get(search_url, query_string=dict(stars='4'))
        assert_hits_len(res, 2)


def test_query_wrong(app, indexed_records, search_url):
    """Test invalid accept header."""
    with app.test_client() as client:
        res = client.get(search_url, query_string={'q': 'test'})
        assert res.status_code == 200

        res = client.get(search_url, query_string={'q': 'test:a'})
        assert res.status_code == 200

        res = client.get(search_url, query_string={'q': 'test:'})
        assert res.status_code == 400

        res = client.get(search_url, query_string={'q': 'test;'})
        assert res.status_code == 200


@pytest.mark.parametrize('app', [dict(
    endpoint=dict(
        search_factory_imp='invenio_records_rest.query.es_search_factory'
    )
)], indirect=['app'])
def test_elasticsearch_exception(app, indexed_records):
    with app.test_client() as client:
        res = client.get(url_for('invenio_records_rest.recid_list', q='i/o'))
        assert res.status_code == 400
        assert ('The syntax of the search query is invalid.' in
                res.get_data(as_text=True))
