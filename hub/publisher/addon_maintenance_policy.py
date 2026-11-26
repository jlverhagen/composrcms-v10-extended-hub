"""Extended release exclusions; retained upstream files are not bundled."""


def is_excluded_spreadsheet_payload(name):
    return (name == 'sources_custom/hooks/systems/addon_registry/excel_support.php'
            or name in {'sources_custom/files2.php', 'sources_custom/files_spout.php'}
            or name == 'sources_custom/spout' or name.startswith('sources_custom/spout/'))
