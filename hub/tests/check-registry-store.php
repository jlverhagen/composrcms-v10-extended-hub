<?php
declare(strict_types=1);

require __DIR__ . '/../operator/registry-store.php';

function check_registry_store(bool $condition): void
{
    if (!$condition) {
        throw new LogicException('Registry store assertion failed');
    }
}

$zero = str_repeat("\0", 32);
$first = extended_registry_generation_evidence('test', 'registry', 0, 1, $zero, 'a', "a\0b", 'c', '{}', '{}');
$second = extended_registry_generation_evidence('test', 'registry', 0, 1, $zero, 'a', 'a', "\0bc", '{}', '{}');
check_registry_store($first !== $second);
check_registry_store(str_starts_with($first, "composr-registry-generation-v1\0"));
check_registry_store(str_contains($first, pack('N', 3) . "a\0b"));

$decoded = extended_decode_registry_generation_evidence($first);
check_registry_store($decoded['manifest'] === "a\0b" && $decoded['generation'] === 0);
foreach ([substr($first, 0, -1), $first . 'x'] as $invalid) {
    try {
        extended_decode_registry_generation_evidence($invalid);
        throw new LogicException('Malformed registry evidence decoded');
    } catch (InvalidArgumentException $error) {
        // Expected rejection.
    }
}

$dsn = getenv('EXTENDED_REGISTRY_TEST_DSN');
if ($dsn === false || $dsn === '') {
    echo "Encoding passed. MariaDB tests skipped (no test DSN).\n";
    exit(0);
}

// Run against a disposable schema initialized with registry-store.sql.
$db = new PDO($dsn, getenv('EXTENDED_REGISTRY_TEST_USER') ?: '', getenv('EXTENDED_REGISTRY_TEST_PASSWORD') ?: '', [
    PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    PDO::ATTR_EMULATE_PREPARES => false,
]);
$deployment = 'test-' . bin2hex(random_bytes(8));
$store = new ExtendedRegistryStore($db, $deployment, 'registry');
check_registry_store($store->head() === null);
$bootstrap = $store->stage(null, 1, 'a', "a\0b", 'c', '{}', '{}');
check_registry_store($store->evidence(...$bootstrap) === extended_registry_generation_evidence(
    $deployment, 'registry', 0, 1, $zero, 'a', "a\0b", 'c', '{}', '{}'
));
check_registry_store($store->head() === null);
$store->activate(null, $bootstrap);
$next = $store->stage($bootstrap, 2, 'b', 'next', 'sig', '{}', '{}');
check_registry_store($store->head() === $bootstrap);
check_registry_store($store->stage($bootstrap, 2, 'b', 'next', 'sig', '{}', '{}') === $next);
$competing = $store->stage($bootstrap, 2, 'c', 'competing', 'sig', '{}', '{}');
// A fresh store instance can recover the staged evidence after interruption.
$resumed = new ExtendedRegistryStore($db, $deployment, 'registry');
check_registry_store($resumed->head() === $bootstrap);
check_registry_store($resumed->evidence(...$next) !== null);
$resumed->activate($bootstrap, $next);
$store->activate($bootstrap, $next);
try {
    $store->activate($bootstrap, $competing);
    throw new LogicException('Competing activation succeeded');
} catch (RuntimeException $error) {
    check_registry_store($error->getMessage() === 'Registry head changed before activation');
}
check_registry_store($store->head() === $next);
echo "Encoding and MariaDB transaction tests passed.\n";

require __DIR__ . '/../operator/registry-commit.php';
$directory = sys_get_temp_dir() . '/registry-commit-' . bin2hex(random_bytes(12));
if (!mkdir($directory, 0700)) {
    throw new RuntimeException('Cannot create test record directory');
}
$path = $directory . '/registry.json';
try {
    $writeFixture = static function (array $head, int $sequence, string $manifest) use ($path, $deployment): void {
        file_put_contents($path, json_encode([
            'version' => 1, 'deployment' => $deployment, 'registry' => 'registry',
            'generation' => $head[0], 'sequence' => $sequence,
            'manifest_digest' => hash('sha256', $manifest), 'state_digest' => bin2hex($head[1]),
        ], JSON_THROW_ON_ERROR));
    };
    $writeFixture($next, 2, 'next');
    $modes = [];
    $operator = new ExtendedRegistryCommit($store, $path, static function (array $before, array $after, bool $resume) use (&$modes): bool {
        $modes[] = $resume;
        return $after['approval_id'] !== 'denied';
    });
    $denied = $store->stage($next, 3, 'denied', 'denied', 'sig', '{}', '{}');
    try {
        $operator->commit($next, $denied);
        throw new LogicException('Denied approval committed');
    } catch (RuntimeException $error) {
        check_registry_store($error->getMessage() === 'Registry approval evidence was rejected');
    }
    check_registry_store($operator->reconcile() === $next);
    $third = $store->stage($next, 3, 'd', 'third', 'sig', '{}', '{}');
    check_registry_store($operator->commit($next, $third) === $third);
    check_registry_store($operator->commit($next, $third) === $third);

    // Model the persisted record immediately after publication, before DB activation.
    $fourth = $store->stage($third, 4, 'e', 'fourth', 'sig', '{}', '{}');
    $writeFixture($fourth, 4, 'fourth');
    check_registry_store($store->head() === $third);
    check_registry_store($operator->reconcile() === $fourth);
    check_registry_store($store->head() === $fourth);
    check_registry_store($modes === [false, false, true]);

    // Model an older restored database with no evidence for the independent head.
    $writeFixture([5, str_repeat("\x7f", 32)], 6, 'missing');
    try {
        $operator->reconcile();
        throw new LogicException('Missing generation was accepted');
    } catch (RuntimeException $error) {
        check_registry_store($error->getMessage() === 'Registry recovery required: generation evidence missing');
    }
    check_registry_store($store->head() === $fourth);
    echo "Registry commit and reconciliation tests passed.\n";
} finally {
    unlink($path);
    unlink($path . '.lock');
    rmdir($directory);
}

require __DIR__ . '/../operator/registry-approval.php';
$deployment .= '-bootstrap';
$registry = 'composrcms-v10-extended';
$store = new ExtendedRegistryStore($db, $deployment, $registry);
$root = sodium_crypto_sign_keypair();
$approver = sodium_crypto_sign_keypair();
$rootKeys = ['root' => base64_encode(sodium_crypto_sign_publickey($root))];
$approvalKeys = ['reviewer' => base64_encode(sodium_crypto_sign_publickey($approver))];
$sign = static fn(string $bytes, string $id, string $key): string => json_encode([
    'algorithm' => 'Ed25519', 'key_id' => $id,
    'signature' => base64_encode(sodium_crypto_sign_detached($bytes, sodium_crypto_sign_secretkey($key))),
], JSON_THROW_ON_ERROR);
$manifest = json_encode([
    'schema_version' => 1, 'registry_id' => $registry, 'sequence' => 1,
    'issued_at' => time() - 1, 'expires_at' => time() + 3600, 'sources' => [],
], JSON_THROW_ON_ERROR);
$signature = $sign($manifest, 'root', $root);
$approval = $sign(extended_registry_approval_claims([
    'deployment' => $deployment, 'registry' => $registry, 'generation' => 0,
    'prior_digest' => $zero, 'approval_id' => 'initial', 'manifest' => $manifest,
    'signature' => $signature, 'policy' => '{}',
]), 'reviewer', $approver);
$initial = $store->stage(null, 1, 'initial', $manifest, $signature, '{}', $approval);
if (!mkdir($directory, 0700)) {
    throw new RuntimeException('Cannot create bootstrap test directory');
}
try {
    $operator = new ExtendedRegistryCommit($store, $path,
        static fn(?array $before, array $after, bool $resume): bool =>
            extended_verify_registry_approval($before, $after, $resume, $rootKeys, $approvalKeys));
    check_registry_store($operator->bootstrap($initial) === $initial);
    check_registry_store($store->head() === $initial);
    check_registry_store($operator->bootstrap($initial) === $initial);
    unlink($path);
    try {
        $operator->bootstrap($initial);
        throw new LogicException('Bootstrap replaced a missing initialized record');
    } catch (RuntimeException $error) {
        check_registry_store(str_starts_with($error->getMessage(), 'Registry bootstrap requires'));
    }
    echo "Signed registry bootstrap tests passed.\n";
} finally {
    if (is_file($path)) {
        unlink($path);
    }
    unlink($path . '.lock');
    rmdir($directory);
}
