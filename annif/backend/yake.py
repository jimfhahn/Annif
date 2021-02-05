"""Annif backend using Yake keyword extraction"""
# TODO Mention GPLv3 license also here?

import yake
import os.path
import re
from collections import defaultdict
from rdflib.namespace import SKOS, RDF, OWL
import rdflib
import annif.util
from . import backend
from annif.suggestion import SubjectSuggestion, ListSuggestionResult
from annif.exception import ConfigurationException


class YakeBackend(backend.AnnifBackend):
    """Yake based backend for Annif"""
    name = "yake"
    needs_subject_index = False

    # defaults for uninitialized instances
    _index = None
    _graph = None
    INDEX_FILE = 'yake-index'

    DEFAULT_PARAMETERS = {
        'max_ngram_size': 4,
        'deduplication_threshold': 0.9,
        'deduplication_algo': 'levs',
        'window_size': 1,
        'num_keywords': 100,
        'features': None,
        'default_label_types': ['pref', 'alt'],
        'remove_parentheses': False
    }

    def default_params(self):
        params = backend.AnnifBackend.DEFAULT_PARAMETERS.copy()
        params.update(self.DEFAULT_PARAMETERS)
        return params

    @property
    def is_trained(self):
        return True

    @property
    def label_types(self):
        mapping = {'pref': SKOS.prefLabel,
                   'alt': SKOS.altLabel,
                   'hidden': SKOS.hiddenLabel}
        if 'label_types' in self.params:
            lt_entries = self.params['label_types'].split(',')
            try:
                return [mapping[lt.strip()] for lt in lt_entries]
            except KeyError as err:
                raise ConfigurationException(
                    f'invalid label type {err}', backend_id=self.backend_id)
        else:
            return [mapping[lt] for lt in self.params['default_label_types']]

    @property
    def graph(self):
        if self._graph is None:
            self.info('Loading graph')
            self._graph = self.project.vocab.as_graph()
        return self._graph

    def initialize(self):
        self._initialize_index()
        self._kw_extractor = yake.KeywordExtractor(
            lan=self.params['language'],
            n=self.params['max_ngram_size'],
            dedupLim=self.params['deduplication_threshold'],
            dedupFunc=self.params['deduplication_algo'],
            windowsSize=self.params['window_size'],
            top=self.params['num_keywords'],
            features=self.params['features'])

    def _initialize_index(self):
        if self._index is None:
            path = os.path.join(self.datadir, self.INDEX_FILE)
            if os.path.exists(path):
                self._index = self._load_index(path)
                self.info(
                    f'Loaded index from {path} with {len(self._index)} labels')
            else:
                self.info('Creating index')
                self._create_index()
                self._save_index(path)
                self.info(f'Created index with {len(self._index)} labels')

    def _save_index(self, path):
        with open(path, 'w', encoding='utf-8') as indexfile:
            for label, uris in self._index.items():
                line = label + '\t' + ' '.join(uris)
                print(line, file=indexfile)

    def _load_index(self, path):
        index = dict()
        with open(path, 'r', encoding='utf-8') as indexfile:
            for line in indexfile:
                label, uris = line.strip().split('\t')
                index[label] = uris.split()
        return index

    def _create_index(self):
        index = defaultdict(set)
        for concept in self.graph.subjects(RDF.type, SKOS.Concept):
            if (concept, OWL.deprecated, rdflib.Literal(True)) in self.graph:
                continue
            uri = str(concept)
            labels = self._get_concept_labels(concept, self.label_types)
            for label in labels:
                label = self._normalize_label(label)
                index[label].add(uri)
        index.pop('', None)  # Remove possible empty string entry
        self._index = dict(index)
    def _get_concept_labels(self, concept, label_types):
        labels = []
        for label_type in label_types:
            for label in self.graph.objects(concept, label_type):
                if label.language == self.params['language']:
                    labels.append(label)
        return labels

    def _normalize_label(self, label):
        label = str(label)
        if annif.util.boolean(self.params['remove_parentheses']):
            label = re.sub(r' \(.*\)', '', label)
        lemmatized_label = self._lemmatize_phrase(label)
        return self._sort_phrase(lemmatized_label)

    def _lemmatize_phrase(self, phrase):
        normalized = []
        for word in phrase.split():
            normalized.append(
                self.project.analyzer.normalize_word(word).lower())
        return ' '.join(normalized)

    def _sort_phrase(self, phrase):
        words = phrase.split()
        return ' '.join(sorted(words))

    def _suggest(self, text, params):
        self.debug(
            f'Suggesting subjects for text "{text[:20]}..." (len={len(text)})')
        limit = int(params['limit'])

        keyphrases = self._kw_extractor.extract_keywords(text)
        suggestions = self._keyphrases2suggestions(keyphrases)

        subject_suggestions = [SubjectSuggestion(
                uri=uri,
                label=None,
                notation=None,
                score=score)
                for uri, score in suggestions[:limit] if score > 0.0]
        return ListSuggestionResult.create_from_index(subject_suggestions,
                                                      self.project.subjects)

    def _keyphrases2suggestions(self, keyphrases):
        suggestions = []
        not_matched = []
        for kp, score in keyphrases:
            uris = self._keyphrase2uris(kp)
            for uri in uris:
                suggestions.append(
                    (uri, self._transform_score(score)))
            if not uris:
                not_matched.append((kp, self._transform_score(score)))
        # Remove duplicate uris, conflating the scores
        suggestions = self._combine_suggestions(suggestions)
        self.debug('Keyphrases not matched:\n' + '\t'.join(
            [kp[0] + ' ' + str(kp[1]) for kp
             in sorted(not_matched, reverse=True, key=lambda kp: kp[1])]))
        return suggestions

    def _keyphrase2uris(self, keyphrase):
        keyphrase = self._lemmatize_phrase(keyphrase)
        keyphrase = self._sort_phrase(keyphrase)
        return self._index.get(keyphrase, [])

    def _transform_score(self, score):
        if score < 0:
            self.debug(f'Replacing negative YAKE score {score} with zero')
            return 1.0
        return 1.0 / (score + 1)

    def _combine_suggestions(self, suggestions):
        combined_suggestions = {}
        for uri, score in suggestions:
            if uri not in combined_suggestions:
                combined_suggestions[uri] = score
            else:
                old_score = combined_suggestions[uri]
                combined_suggestions[uri] = self._conflate_scores(
                    score, old_score)
        return list(combined_suggestions.items())

    def _conflate_scores(self, score1, score2):
        return score1 * score2 / (score1 * score2 + (1-score1) * (1-score2))
