<?php
// Run only in an isolated temporary directory. The stock TAR reader is supplied by the caller.
function mixed() { return null; }
function do_lang_tempcode($message) { return $message; }
function warn_exit($message) { throw new RuntimeException($message); }
function afm_make_directory($path, $world_access) {}
function afm_make_file($path, $contents, $world_access)
{
    global $root, $writes;
    if ($writes === 1) {
        throw new RuntimeException('Injected second write failure');
    }
    if (file_put_contents($root . '/' . basename($path), $contents) !== strlen($contents)) {
        throw new LogicException('Fixture write failed');
    }
    $writes++;
}
function verify_state($condition, $message)
{
    if (!$condition) {
        throw new LogicException($message);
    }
}
if ($argc !== 3) {
    fwrite(STDERR, "Usage: php check-stock-file-recovery.php sources/tar.php theme-fixture.tar\n");
    exit(2);
}
require $argv[1];
$root = sys_get_temp_dir() . '/extended-recovery-' . bin2hex(random_bytes(12));
verify_state(mkdir($root, 0700), 'Could not create fixture directory');
$tar = tar_open($argv[2], 'rb');
try {
    $paths = array_column(tar_get_directory($tar), 'path');
    $selected = array_slice(array_values(array_filter($paths, fn($path) => str_ends_with($path, '.css'))), 0, 2);
    verify_state(count($selected) === 2 && basename($selected[0]) !== basename($selected[1]), 'Expected two distinct CSS entries');
    $first = $root . '/' . basename($selected[0]);
    $second = $root . '/' . basename($selected[1]);
    $backup = $root . '/baseline';
    file_put_contents($first, 'original');
    verify_state(copy($first, $backup), 'Could not snapshot fixture');
    $digest = hash_file('sha256', $backup);
    $writes = 0;
    try {
        tar_extract_to_folder($tar, '', true, $selected, false);
        throw new LogicException('Expected injected failure');
    } catch (RuntimeException $error) {
        verify_state($error->getMessage() === 'Injected second write failure', $error->getMessage());
    }
    verify_state($writes === 1 && hash_file('sha256', $first) !== $digest && !file_exists($second),
        'Partial filesystem state did not match the expected interruption');
    verify_state(copy($backup, $first), 'Restore failed');
    verify_state(hash_file('sha256', $first) === $digest && !file_exists($second), 'Restored files differ from baseline');
    echo PHP_VERSION, ': partial write reproduced and original filesystem bytes restored', PHP_EOL;
} finally {
    tar_close($tar);
    foreach (glob($root . '/*') as $file) {
        unlink($file);
    }
    rmdir($root);
}
