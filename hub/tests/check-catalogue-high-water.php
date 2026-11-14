<?php
require __DIR__ . '/../../cms/sources_custom/extended_catalogue_high_water.php';

$root = sys_get_temp_dir() . '/catalogue-water-' . bin2hex(random_bytes(12));
mkdir($root, 0700);
$path = $root . '/record.json';
$pair = sodium_crypto_sign_keypair();
$keys = ['key' => base64_encode(sodium_crypto_sign_publickey($pair))];
$now = time();
$manifest = fn($issued, $expires) => json_encode([
    'schema_version' => 1, 'source_id' => 'test', 'issued_at' => $issued,
    'expires_at' => $expires, 'addons' => [],
], JSON_THROW_ON_ERROR);
$approve = function ($bytes) use ($path, $pair, $keys, $now) {
    $signature = json_encode(['algorithm' => 'Ed25519', 'key_id' => 'key',
        'signature' => base64_encode(sodium_crypto_sign_detached($bytes, sodium_crypto_sign_secretkey($pair)))]);
    return extended_approve_catalogue_high_water($path, 'test', $bytes, $signature, $keys, ['key'], $now);
};
$reject = function ($action) {
    try {
        $action();
    } catch (RuntimeException $e) {
        return;
    }
    throw new LogicException('Expected rejection');
};
try {
    $old = $manifest($now - 2, $now + 100);
    $new = $manifest($now - 1, $now + 100);
    $reject(fn() => $approve($old));
    file_put_contents($path, '{"version":1,"sources":{}}');
    chmod($path, 0640);
    $approve($old);
    $approve($new);
    $approve($new);
    $reject(fn() => $approve($old));
    $reject(fn() => $approve($manifest($now - 1, $now + 101)));
    $reject(fn() => extended_assert_approved_catalogue($path, 'test', $now - 2, $old));
    extended_assert_approved_catalogue($path, 'test', $now - 1, $new);
    if ((fileperms($path) & 0777) !== 0640) throw new LogicException('Record mode changed');
    echo "Catalogue approval checks passed\n";
} finally {
    foreach (glob($root . '/*') as $file) unlink($file);
    rmdir($root);
}
