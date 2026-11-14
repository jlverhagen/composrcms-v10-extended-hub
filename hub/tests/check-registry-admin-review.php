<?php

require __DIR__ . '/../../cms/sources_custom/extended_registry_admin_review.php';
$path = tempnam(sys_get_temp_dir(), 'registry-review-');
$review = [
    'claims' => json_encode(['schema_version' => 1, 'purpose' => 'composr-registry-approval']),
    'expires_at' => 100, 'prior_sources' => [], 'proposed_sources' => [],
];
try {
    file_put_contents($path, json_encode($review));
    [$loaded, $digest] = extended_registry_admin_review($path, null, 99);
    if ($loaded !== $review) {
        throw new LogicException('Review mismatch');
    }
    extended_registry_admin_review($path, $digest, 99);

    foreach (['changed', 'expired'] as $case) {
        if ($case === 'changed') {
            file_put_contents($path, json_encode(array_replace($review, ['sequence' => 2])));
        } else {
            file_put_contents($path, json_encode($review));
        }
        try {
            extended_registry_admin_review($path, $digest, $case === 'expired' ? 100 : 99);
            throw new LogicException('Accepted ' . $case . ' review');
        } catch (RuntimeException $expected) {
            // Expected rejection.
        }
    }
    foreach (['GET', 'POST'] as $method) {
        $_SERVER['REQUEST_METHOD'] = $method;
        try {
            extended_run_registry_admin_review('approve_registry', 1);
            throw new LogicException('Accepted an unprotected request');
        } catch (RuntimeException $expected) {
            if ($expected->getMessage() !== 'Registry approval requires a protected POST') {
                throw $expected;
            }
        }
    }
    echo "Registry Admin Zone review checks passed.\n";
} finally {
    unlink($path);
}

require __DIR__ . '/../../cms/adminzone/pages/modules_custom/admin_extended_addons.php';

function get_member() { return 7; }
function access_denied($code) { throw new DomainException('Access denied'); }
function csrf_filter_active() { return $GLOBALS['test_csrf_active'] ?? false; }
function get_param_string($name, $default) { return 'approve_registry'; }
function require_code($name) {}
function warn_exit($message) { throw new DomainException($message); }
function post_param_string($name) { return $GLOBALS['test_review_digest']; }
function make_string_tempcode($html) { return $html; }
function escape_html($text) { return htmlspecialchars($text, ENT_QUOTES, 'UTF-8'); }

$GLOBALS['FORUM_DRIVER'] = new class {
    public function is_super_admin($member) { return false; }
};
try {
    (new Module_admin_extended_addons())->run();
    throw new LogicException('Non-super-admin reached registry routing');
} catch (DomainException $expected) {
    // The existing module authorization must run before route dispatch.
}

$_SERVER['REQUEST_METHOD'] = 'POST';
$GLOBALS['CSRF_TOKENS'] = true;
try {
    extended_run_registry_admin_review('approve_registry', 7);
    throw new LogicException('POST without active CSRF filter accepted');
} catch (RuntimeException $expected) {
    if ($expected->getMessage() !== 'Registry approval requires a protected POST') {
        throw $expected;
    }
}

$directory = sys_get_temp_dir() . '/registry-receipt-' . bin2hex(random_bytes(12));
mkdir($directory, 0700);
$receipt = ['member_id' => 7, 'review_sha256' => $digest, 'claims' => $review['claims'], 'confirmed_at' => 99];
try {
    $saved = extended_store_registry_review_receipt($directory, $receipt);
    $retry = extended_store_registry_review_receipt($directory, array_replace($receipt, ['confirmed_at' => 100]));
    if ($saved !== $receipt || $retry !== $receipt || count(scandir($directory)) !== 3) {
        throw new LogicException('Registry receipt retry changed the original record');
    }
} finally {
    unlink($directory . '/' . $digest . '-7.json');
    rmdir($directory);
}
echo "Persistent registry receipt checks passed.\n";

// Exercise the actual module dispatch and confirmation handler with Composr API stubs.
mkdir($directory, 0700);
$path = $directory . '/review.json';
define('EXTENDED_REGISTRY_REVIEW_PATH', $path);
define('EXTENDED_REGISTRY_RECEIPT_DIRECTORY', $directory);
$review['expires_at'] = time() + 60;
$bytes = json_encode($review);
file_put_contents($path, $bytes);
$GLOBALS['test_review_digest'] = hash('sha256', $bytes);
$GLOBALS['FORUM_DRIVER'] = new class {
    public function is_super_admin($member) { return $member === 7; }
};
$module = new Module_admin_extended_addons();
try {
    foreach ([['GET', true], ['POST', false]] as [$method, $active]) {
        $_SERVER['REQUEST_METHOD'] = $method;
        $GLOBALS['test_csrf_active'] = $active;
        try {
            $module->run();
            throw new LogicException('Module accepted an unprotected confirmation');
        } catch (DomainException $expected) {
            if (!str_contains($expected->getMessage(), 'could not be completed')) {
                throw $expected;
            }
        }
        if (count(scandir($directory)) !== 3) {
            throw new LogicException('Rejected confirmation wrote a receipt');
        }
    }
    $_SERVER['REQUEST_METHOD'] = 'POST';
    $GLOBALS['test_csrf_active'] = true;
    if (!str_contains($module->run(), 'Registry review confirmed') || count(scandir($directory)) !== 4) {
        throw new LogicException('Protected confirmation did not persist a receipt');
    }
} finally {
    foreach (glob($directory . '/*.json') as $file) {
        unlink($file);
    }
    rmdir($directory);
}
echo "Registry confirmation dispatch checks passed.\n";
