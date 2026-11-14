<?php
function mixed() { return null; }
function require_code($name) { require_once $GLOBALS['argv'][1]; }
function do_lang_tempcode($message) { return $message; }
function warn_exit($message) { throw new RuntimeException($message); }
function better_parse_ini_file($path, $bytes) { return parse_ini_string($bytes, false, INI_SCANNER_RAW); }
function expect_rejection($action, $message) {
    try {
        $action();
    } catch (RuntimeException $error) {
        if ($error->getMessage() === $message) {
            return;
        }
        throw $error;
    }
    throw new LogicException('Expected rejection: ' . $message);
}
if ($argc !== 5) {
    fwrite(STDERR, "Usage: php check-stock-handoff.php /absolute/path/to/stock/tar.php flat.tar nested.tar theme.tar" . PHP_EOL);
    exit(2);
}
require __DIR__ . '/../../cms/sources_custom/extended_local_addon_handoff.php';
foreach (array_slice($argv, 2) as $index => $path) {
    $id = ['extended_export_smoke_20261112', 'extended_nested_smoke', 'extended_theme_smoke'][$index];
    $preview = extended_preview_local_addon_handoff($path, 'fixture', $id, hash_file('sha256', $path));
    $choice = array_slice($preview['selectable_paths'], 0, 1);
    if (extended_confirm_local_addon_handoff($path, $preview, $choice) !== $choice) {
        throw new LogicException('Valid selection was not preserved');
    }
    foreach ([['addon.inf'], ['not-reviewed.txt'], [$choice[0], $choice[0]]] as $selection) {
        expect_rejection(fn() => extended_confirm_local_addon_handoff($path, $preview, $selection),
            'Unreviewed or duplicate addon file selection');
    }
    expect_rejection(fn() => extended_confirm_local_addon_handoff($path, $preview, []),
        'Select at least one reviewed addon file');
    $different = $preview;
    $different['inventory'] = array_slice($different['inventory'], 0, 1, true);
    expect_rejection(fn() => extended_confirm_local_addon_handoff($path, $different, $choice),
        'Archive no longer matches the reviewed preview');
    $temp = tempnam(sys_get_temp_dir(), 'extended-handoff-');
    try {
        file_put_contents($temp, file_get_contents($path) . str_repeat("\0", 512));
        expect_rejection(fn() => extended_confirm_local_addon_handoff($temp, $preview, $choice),
            'Package checksum mismatch');
    } finally {
        unlink($temp);
    }
    echo basename($path), ': ', count($preview['inventory']), ' entries; handoff checks passed', PHP_EOL;
}

require __DIR__ . '/../../cms/sources_custom/extended_addon_confirmation.php';
$directory = sys_get_temp_dir() . '/extended-confirm-' . bin2hex(random_bytes(12));
if (!mkdir($directory, 0700)) {
    throw new RuntimeException('Could not create test directory');
}
$archive = $directory . '/fixture.tar';
try {
    copy($argv[2], $archive);
    $original = file_get_contents($archive);
    $id = 'extended_export_smoke_20261112';
    $digest = hash('sha256', $original);
    $create = fn() => extended_create_addon_confirmation($directory, 10, $archive, 'fixture', $id, $digest);
    $finish = fn($token, $paths, $admin = 10) => extended_finish_addon_confirmation($directory, $admin, $token, $paths);
    $first = $create();
    expect_rejection(fn() => $finish($first['token'], $first['selectable_paths'], 11), 'Confirmation is unavailable');
    expect_rejection(fn() => $finish($first['token'], ['not-reviewed.txt']), 'Unreviewed or duplicate addon file selection');
    $checked = $finish($first['token'], $first['selectable_paths']);
    if ($checked['archive_path'] !== $archive || $checked['source_id'] !== 'fixture'
        || $checked['sha256'] !== $digest || $checked['selected_paths'] !== $first['selectable_paths']) {
        throw new LogicException('Confirmed archive metadata did not match the preview');
    }
    expect_rejection(fn() => $finish($first['token'], $first['selectable_paths']), 'Confirmation is unavailable');

    $cancelled = $create();
    if ($finish($cancelled['token'], null) !== null) {
        throw new LogicException('Cancellation returned install details');
    }
    expect_rejection(fn() => $finish($cancelled['token'], $cancelled['selectable_paths']), 'Confirmation is unavailable');

    $expired = $create();
    $record_path = $directory . '/' . $expired['token'];
    $record = json_decode(file_get_contents($record_path), true, 512, JSON_THROW_ON_ERROR);
    $record['expires_at'] = time() - 1;
    file_put_contents($record_path, json_encode($record, JSON_THROW_ON_ERROR));
    expect_rejection(fn() => $finish($expired['token'], $expired['selectable_paths']), 'Confirmation has expired');

    $changed = $create();
    file_put_contents($archive, str_repeat("\0", 512), FILE_APPEND);
    expect_rejection(fn() => $finish($changed['token'], $changed['selectable_paths']), 'Package checksum mismatch');
    $finish($changed['token'], null);
    if (scandir($directory) !== ['.', '..', 'fixture.tar']) {
        throw new LogicException('Unexpected confirmation state left after the checks');
    }
    echo 'Confirmation ownership, selection, replay, cancellation, expiry and digest checks passed', PHP_EOL;
} finally {
    foreach (scandir($directory) as $file) {
        if ($file !== '.' && $file !== '..') {
            unlink($directory . '/' . $file);
        }
    }
    rmdir($directory);
}
