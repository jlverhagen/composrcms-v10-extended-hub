<?php
declare(strict_types=1);

require __DIR__ . '/../operator/registry-approval.php';

function signed_envelope(string $bytes, string $id, string $pair): string
{
    return json_encode([
        'algorithm' => 'Ed25519', 'key_id' => $id,
        'signature' => base64_encode(sodium_crypto_sign_detached($bytes, sodium_crypto_sign_secretkey($pair))),
    ], JSON_THROW_ON_ERROR);
}

$root = sodium_crypto_sign_keypair();
$approver = sodium_crypto_sign_keypair();
$roots = ['root' => base64_encode(sodium_crypto_sign_publickey($root))];
$approvers = ['operator' => base64_encode(sodium_crypto_sign_publickey($approver))];
$now = time();
$registry = 'composrcms-v10-extended';
$manifest = json_encode([
    'schema_version' => 1, 'registry_id' => $registry, 'sequence' => 2,
    'issued_at' => $now - 10, 'expires_at' => $now + 10, 'sources' => [],
], JSON_THROW_ON_ERROR);
$signature = signed_envelope($manifest, 'root', $root);
$prior = random_bytes(32);
$claims = json_encode([
    'schema_version' => 1, 'purpose' => 'composr-registry-approval',
    'deployment' => 'test', 'registry' => $registry, 'generation' => 1,
    'prior_digest' => bin2hex($prior), 'approval_id' => 'reviewed',
    'manifest_digest' => hash('sha256', $manifest), 'signature_digest' => hash('sha256', $signature),
    'policy_digest' => hash('sha256', '{}'),
], JSON_THROW_ON_ERROR);
$before = ['policy' => '{}', 'sequence' => 1, 'manifest' => 'prior'];
$after = [
    'deployment' => 'test', 'registry' => $registry, 'generation' => 1, 'sequence' => 2,
    'prior_digest' => $prior, 'approval_id' => 'reviewed', 'manifest' => $manifest,
    'signature' => $signature, 'policy' => '{}', 'approval' => signed_envelope($claims, 'operator', $approver),
];
extended_verify_registry_approval($before, $after, false, $roots, $approvers, $now);
extended_verify_registry_approval($before, $after, true, $roots, $approvers, $now + 11);
foreach ([
    [$after, $now + 11],
    [array_replace($after, ['deployment' => 'other']), $now],
    [array_replace($after, ['prior_digest' => random_bytes(32)]), $now],
    [array_replace($after, ['policy' => '{"different":true}']), $now],
    [array_replace($after, ['manifest' => $manifest . ' ']), $now],
    [array_replace($after, ['approval' => signed_envelope($claims, 'operator', $root)]), $now],
] as [$candidate, $clock]) {
    try {
        extended_verify_registry_approval($before, $candidate, false, $roots, $approvers, $clock);
        throw new LogicException('Invalid approval was accepted');
    } catch (RuntimeException $expected) {
        // The fixture must fail verification.
    }
}
echo "Signed registry approval tests passed.\n";
