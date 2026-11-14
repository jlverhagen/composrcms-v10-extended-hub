#!/usr/bin/env python3
"""Merge catalogues already verified by the caller against approved registry sources."""


def merge(registry, catalogues):
    sources = {}
    for source in registry['sources']:
        source_id = source['id']
        if source_id in sources:
            raise ValueError('duplicate registry source: ' + source_id)
        sources[source_id] = source

    results = {}
    for source_id, catalogue in catalogues.items():
        source = sources.get(source_id)
        if source is None or source.get('enabled') is not True:
            raise ValueError('source is not approved: ' + source_id)
        if catalogue.get('source_id') != source_id or catalogue.get('schema_version') != 1:
            raise ValueError('source mismatch')
        priority = source.get('priority', 0)
        if type(priority) is not int:
            raise ValueError('invalid registry priority for source: ' + source_id)
        for addon in catalogue.get('addons', []):
            key = (source_id, addon['id'])
            if key in results:
                raise ValueError('duplicate addon within source')
            results[key] = {**addon, 'source_id': source_id, 'priority': priority}
    return sorted(results.values(), key=lambda addon: (addon['id'], -addon['priority'], addon['source_id']))
