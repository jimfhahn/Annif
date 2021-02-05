"""Unit tests for the Yake backend in Annif"""

import annif
import pytest
import os
from rdflib import Graph
import annif.backend


pytest.importorskip("annif.backend.yake")


@pytest.fixture(scope='module')
def graph_project(project):
    _rdf_file_path = os.path.join(
        os.path.dirname(__file__),
        'corpora',
        'archaeology',
        'yso-archaeology.rdf')
    g = Graph()
    g.load(_rdf_file_path)
    project.vocab.as_graph.return_value = g
    return project


def test_yake_suggest(project, graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=graph_project)

    results = yake.suggest("""Arkeologia on tieteenala, jota sanotaan joskus
        muinaistutkimukseksi tai muinaistieteeksi. Se on humanistinen tiede
        tai oikeammin joukko tieteitä, jotka tutkivat ihmisen menneisyyttä.
        Tutkimusta tehdään analysoimalla muinaisjäännöksiä eli niitä jälkiä,
        joita ihmisten toiminta on jättänyt maaperään tai vesistöjen
        pohjaan.""")

    assert len(results) > 0
    assert len(results) <= 8
    hits = results.as_list(project.subjects)
    assert 'http://www.yso.fi/onto/yso/p1265' in [
        result.uri for result in hits]
    assert 'arkeologia' in [result.label for result in hits]


def test_yake_suggest_non_alphanum_text(project, graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=graph_project)

    results = yake.suggest(".,!")
    assert len(results) == 0


def test_create_index_preflabels(graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi', 'label_types': 'pref'},
        project=graph_project)
    index = yake._create_index()
    # Some of the 130 prefLabels get merged in lemmatization:
    # assyriologit, assyriologia (assyriolog); arkealogit, arkeologia
    # (arkeolog); egyptologit, egyptologia (egyptolog)
    assert len(index) == 127
    assert 'kalliotaid' in index
    assert 'luolamaalauks' not in index


def test_create_index_altlabels(graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi', 'label_types': 'alt'},
        project=graph_project)
    index = yake._create_index()
    assert len(index) == 34
    assert 'kalliotaid' not in index
    assert 'luolamaalauks' in index


def test_create_index_pref_and_altlabels(graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=graph_project)
    index = yake._create_index()
    assert len(index) == 161
    assert 'kalliotaid' in index
    assert 'luolamaalauks' in index


def test_create_index_label_languages(graph_project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'sv', 'label_types': 'pref'},
        project=graph_project)
    index = yake._create_index()
    assert len(index) == 130
    assert 'kalliotaid' not in index
    assert 'bergkonst' in index
    assert 'rock art' not in index


def test_combine_suggestions_different_uris(project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=project)

    suggestions = [('http://www.yso.fi/onto/yso/p1265', 0.75),
                   ('http://www.yso.fi/onto/yso/p1266', 0.25)]
    combined = yake._combine_suggestions(suggestions)
    assert len(combined) == 2
    assert combined[0] == suggestions[0]
    assert combined[1] == suggestions[1]


def test_combine_suggestions_same_uri(project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=project)

    combined = yake._combine_suggestions(
        [('http://www.yso.fi/onto/yso/p1265', 0.42),
         ('http://www.yso.fi/onto/yso/p1265', 0.42)])
    assert len(combined) == 1


def test_combine_scores(project):
    yake_type = annif.backend.get_backend('yake')
    yake = yake_type(
        backend_id='yake',
        config_params={'limit': 8, 'language': 'fi'},
        project=project)

    assert yake._combine_scores(0.5, 0.5) == 0.8
    assert yake._combine_scores(0.75, 0.75) == 0.96
    assert yake._combine_scores(1.0, 0.424242) == 1.0
    assert yake._combine_scores(1.0, 0.0) == 1.0
    assert yake._combine_scores(0.4, 0.3) == 0.625
    assert yake._combine_scores(0.4, 0.5) == 0.75
