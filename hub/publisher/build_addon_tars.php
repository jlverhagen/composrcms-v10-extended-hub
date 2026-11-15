<?php
/**
 * Offline counterpart to the homesite's build_addons minimodule.
 *
 * Usage: php build_addon_tars.php CORE_CHECKOUT OUTPUT_DIRECTORY [ADDON_ID ...]
 * Run against a trusted, clean Composr source checkout. Registry hooks are PHP code.
 */

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

$source = realpath($argv[1] ?? '');
$output = isset($argv[2]) ? realpath($argv[2]) : false;
if ($argc < 3 || $source === false || !is_file($source . '/sources/addons2.php')
    || $output === false || !is_dir($output) || !is_writable($output)
    || $output === $source || str_starts_with($output, $source . '/')) {
    fwrite(STDERR, "Usage: php build_addon_tars.php CORE_CHECKOUT EXISTING_OUTPUT_DIRECTORY [ADDON_ID ...]\n");
    exit(2);
}

const HHVM = false;
const GOOGLE_APPENGINE = true;
function running_script($name) { return false; }
$GLOBALS['DEV_MODE'] = false;
$GLOBALS['SITE_INFO'] = array('prefer_direct_code_call' => '1');
$GLOBALS['FORUM_DRIVER'] = new class {
    public function get_theme() { return 'default'; }
};

function get_file_base() { return $GLOBALS['source']; }
function get_custom_file_base() { return $GLOBALS['output']; }
function get_param_string($name, $default = null) { return $default; }
function get_param_integer($name, $default = null) { return $default; }
function sync_file($filename) {}
function cms_srv($name) { return ''; }
function warn_exit($message) { throw new RuntimeException((string) $message); }
function do_lang_tempcode($key, ...$details) { return implode(' ', array_merge(array($key), $details)); }

function filter_naughty($path)
{
    if (!preg_match('~\A[^/\x00-\x1f\x7f:]+(?:/[^/\x00-\x1f\x7f:]+)*\z~D', $path)
        || str_contains($path, chr(92))
        || array_intersect(explode('/', $path), array('.', '..'))) {
        throw new RuntimeException("Invalid package path: $path");
    }
    return $path;
}

function filter_naughty_harsh($path, $preg = false) { return filter_naughty($path); }

function require_code($name)
{
    $name = filter_naughty($name);
    $custom = get_file_base() . '/sources_custom/' . $name . '.php';
    require_once is_file($custom) ? $custom : get_file_base() . '/sources/' . $name . '.php';
}

function require_package_file($path)
{
    $full = get_file_base() . '/' . filter_naughty($path);
    if (realpath($full) !== $full || !is_file($full) || !is_readable($full)) {
        throw new RuntimeException("Missing or unsupported source file: $path");
    }
    // The signed catalogue accepts standard USTAR paths, without GNU LongLink records.
    if (strlen($path) > 100 && (!function_exists('tar_split_ustar_path') || tar_split_ustar_path($path) === null)) {
        throw new RuntimeException("Path exceeds the catalogue-compatible TAR limit: $path");
    }
}

foreach (array('global3', 'zones', 'version', 'version2', 'addons', 'addons2', 'tar') as $module) {
    require_code($module);
}

$registry = $source . '/sources_custom/hooks/systems/addon_registry/';
$ids = array_slice($argv, 3);
if ($ids === array()) {
    $ids = array_map(static fn ($path) => basename($path, '.php'), glob($registry . '*.php'));
}
if ($ids === array()) {
    fwrite(STDERR, "No non-bundled addon registry hooks found.\n");
    exit(2);
}

$failed = false;
foreach (array_unique($ids) as $id) {
    $stage = null;
    try {
        if (!preg_match('/\A[A-Za-z0-9_]+\z/', $id) || !is_file($registry . $id . '.php')
            || is_file($source . '/sources/hooks/systems/addon_registry/' . $id . '.php')) {
            throw new RuntimeException('Expected a non-bundled addon registry hook.');
        }
        require_package_file('sources_custom/hooks/systems/addon_registry/' . $id . '.php');
        $info = read_addon_info($id, false, null, null, $registry . $id . '.php');
        $files = array_values(array_filter($info['files'], static fn ($file) => $file !== 'addon.inf' && !str_ends_with($file, '.editfrom')));
        if ($files === array() || count($files) !== count(array_unique($files))) {
            throw new RuntimeException('Expected a non-empty list of unique payload files.');
        }
        foreach ($files as $file) {
            require_package_file($file);
            if (file_exists($source . '/' . $file . '.editfrom')) {
                require_package_file($file . '.editfrom');
            }
            if (preg_match('~^themes/(?!default/|admin/)[^/]+/theme\.ini$~', $file)) {
                throw new RuntimeException('Theme export requires a configured Composr site.');
            }
        }

        $filename = $id . '-' . get_version_branch(floatval($info['version'])) . '.tar';
        $stage = '.addon-build-' . bin2hex(random_bytes(12));
        if (!mkdir($output . '/' . $stage, 0700)) {
            throw new RuntimeException('Could not create a staging directory.');
        }
        create_addon(
            $filename, $files, $info['name'], implode(',', $info['incompatibilities']),
            implode(',', $info['dependencies']), $info['author'], $info['organisation'],
            $info['version'], $info['category'], implode("\n", $info['copyright_attribution']),
            $info['licence'], $info['description'], $stage, null, $source
        );
        $archive = $output . '/' . $stage . '/' . $filename;
        if (!chmod($archive, 0644) || !rename($archive, $output . '/' . $filename)) {
            throw new RuntimeException('Could not move the archive into the output directory.');
        }
        echo $filename . "\n";
    } catch (Throwable $error) {
        fwrite(STDERR, $id . ': ' . $error->getMessage() . "\n");
        $failed = true;
    } finally {
        if ($stage !== null && is_dir($output . '/' . $stage)) {
            foreach (glob($output . '/' . $stage . '/*.tar') as $temporary) {
                unlink($temporary);
            }
            rmdir($output . '/' . $stage);
        }
    }
}
exit($failed ? 1 : 0);
