<?php
// Isolated controller harness. Stock template and installer calls are recorded.
class TestTempcode
{
    public $parts = array();
    public function __construct($name, $parameters = array()) { $this->parts[$name] = $parameters; }
    public function attach($part) { $this->parts += $part->parts; }
}

function require_code($name)
{
    if ($name === 'extended_addon_confirmation') {
        require_once $GLOBALS['argv'][1] . '/sources_custom/' . $name . '.php';
    }
}

function get_file_base() { return $GLOBALS['argv'][2] . '/web'; }
function get_custom_file_base() { return get_file_base(); }
function csrf_filter_active() { return $GLOBALS['csrf_enabled']; }
function appengine_live_guard() {}
function access_denied($message) { throw new RuntimeException('Denied'); }
function post_param_string($key) { return $_POST[$key]; }
function get_value($key) { return $GLOBALS['uses_ftp']; }
function build_url($parameters, $zone) { return $parameters['type']; }
function redirect_screen($title, $url, $message) { return $message; }
function get_screen_title($title) { return $title; }
function do_lang_tempcode($message) { return $message; }
function do_template($name, $parameters) { return new TestTempcode($name, $parameters); }
function escape_html($value) { return htmlspecialchars($value, ENT_QUOTES, 'UTF-8'); }
function make_string_tempcode($value) { return $value; }
function get_version_dotted() { return '10.0.52'; }
function extended_browser_config_from_file($path) { return array(); }
function extended_browser_load($config)
{
    return array('addons' => array('test:fixture' => array(
        'id' => 'fixture', 'source_id' => 'test', 'sha256' => $GLOBALS['approved_digest'],
        'php_minimum' => '8.2', 'cms_minimum' => '10.0.52',
    )));
}
function tar_open($archive, $mode) { return $archive; }
function tar_close($archive) {}
function tar_get_directory(&$tar)
{
    return array(
        0 => array('path' => 'addon.inf', 'size' => 15),
        1024 => array('path' => 'assets/readme.txt', 'size' => 8),
    );
}
function tar_get_file(&$tar, $name) { return array('data' => "name=\"fixture\"\n", 'size' => 15); }
function better_parse_ini_file($path, $content) { return parse_ini_string($content); }

function inform_about_addon_install($name, $uninstalling, $installing, $always_return, $verified_local_path)
{
    test_check($verified_local_path === $GLOBALS['staged_archive'] && $always_return, 'Unexpected preview archive');
    return array('warnings', 'file list', array(
        'name' => 'fixture', 'author' => 'Tester', 'organisation' => 'Test',
        'version' => '1', 'category' => 'Test', 'copyright_attribution' => array(),
        'licence' => 'Test', 'description' => '<fixture>',
    ));
}

function install_addon($name, $files, $do_files, $do_db, $verified_local_path)
{
    test_check($name === 'fixture.tar' && $verified_local_path === $GLOBALS['staged_archive'], 'Unexpected installer archive');
    test_check($files === array('assets/readme.txt') && $do_files && $do_db, 'Unexpected install selection');
    test_check($_POST === array('uses_ftp' => '0'), 'Stock file manager did not receive local-only input');
    $GLOBALS['install_calls']++;
    if ($GLOBALS['fail_install']) {
        throw new RuntimeException('Injected install failure');
    }
}

function test_check($condition, $message)
{
    if (!$condition) {
        throw new LogicException($message);
    }
}
function test_reject($action, $expected)
{
    try {
        $action();
    } catch (RuntimeException $e) {
        test_check($e->getMessage() === $expected, $e->getMessage());
        return;
    }
    throw new LogicException('Expected rejection: ' . $expected);
}

require $argv[1] . '/sources_custom/extended_addon_install_controller.php';
define('EXTENDED_LOCAL_ADDON_DIRECTORY', $argv[2] . '/private');
define('EXTENDED_BROWSER_CONFIG_PATH', 'fixture');
mkdir(get_file_base(), 0700);
mkdir(EXTENDED_LOCAL_ADDON_DIRECTORY, 0700);
$approved_digest = $argv[4];
$staged_archive = EXTENDED_LOCAL_ADDON_DIRECTORY . '/' . $approved_digest . '.tar';
copy($argv[3], $staged_archive);
chmod($staged_archive, 0400);
$CURRENT_SHARE_USER = null;
$CSRF_TOKENS = true;
$csrf_enabled = true;
$uses_ftp = '0';
$install_calls = 0;
$fail_install = false;
$_SERVER['REQUEST_METHOD'] = 'POST';

$review = function () {
    $_POST = array('addon' => 'test:fixture');
    $screen = extended_run_local_addon_install('review_local_addon', 1);
    $stock = $screen->parts['ADDON_INSTALL_CONFIRM_SCREEN'];
    test_check($stock['DESCRIPTION'] === '&lt;fixture&gt;', 'Description was not escaped');
    test_check($stock['FILE'] === $screen->parts['EXTENDED_ADDON_INSTALL_CANCEL']['FILE'], 'Cancel token mismatch');
    return $stock['FILE'];
};
$confirm = function ($token) {
    $_POST = array('file' => $token, 'file_0' => 'assets/readme.txt', 'ftp_domain' => 'ignored');
    return extended_run_local_addon_install('confirm_local_addon', 1);
};
$csrf_enabled = false;
test_reject($review, 'Denied');
$csrf_enabled = true;
$_SERVER['REQUEST_METHOD'] = 'GET';
test_reject($review, 'Denied');
$_SERVER['REQUEST_METHOD'] = 'POST';

$token = $review();
$_POST = array('file' => $token);
extended_run_local_addon_install('cancel_local_addon', 1);
test_reject(fn() => $confirm($token), 'Confirmation is unavailable');
$token = $review();
$uses_ftp = '1';
test_reject(fn() => $confirm($token), 'The local addon handoff requires the local file manager');
$uses_ftp = '0';
symlink(EXTENDED_LOCAL_ADDON_DIRECTORY, get_file_base() . '/assets');
test_reject(fn() => $confirm($token), 'An addon destination parent is not a real directory');
unlink(get_file_base() . '/assets');
$token = $review();
$approved_digest = str_repeat('a', 64);
test_reject(fn() => $confirm($token), 'The approved catalogue entry has changed');
$approved_digest = $argv[4];
test_check($install_calls === 0, 'A rejected request reached the installer');

$token = $review();
$fail_install = true;
test_reject(fn() => $confirm($token), 'Injected install failure');
test_reject(fn() => $confirm($token), 'Confirmation is unavailable');
$fail_install = false;
$token = $review();
test_check($confirm($token) === 'SUCCESS', 'Valid confirmation did not finish');
test_check($_POST['file'] === $token && $install_calls === 2, 'Unexpected request state or installer calls');
echo "Controller checks passed\n";
