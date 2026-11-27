"""Extended release exclusions; retained upstream files are not bundled."""


def is_excluded_spreadsheet_payload(name):
    return (name == 'sources_custom/hooks/systems/addon_registry/excel_support.php'
            or name in {'sources_custom/files2.php', 'sources_custom/files_spout.php'}
            or name == 'sources_custom/spout' or name.startswith('sources_custom/spout/'))


def is_excluded_nested_csv_payload(name):
    return name in {
        'sources_custom/hooks/systems/addon_registry/nested_cpf_csv_lists.php',
        'sources_custom/miniblocks/nested_csv_lists_javascript.php',
        'sources_custom/nested_csv.php',
        'lang_custom/EN/nested_csv.ini',
    }
