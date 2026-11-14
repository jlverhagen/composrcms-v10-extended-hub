<?php
declare(strict_types=1);

require_once __DIR__ . '/../../cms/sources_custom/extended_manifest_verify.php';
require_once __DIR__ . '/../../cms/sources_custom/extended_registry_trust.php';

/**
 * Verify a normal registry update using independently provisioned pins.
 * Root rotation and policy changes require a separate authorization flow.
 */
function extended_verify_registry_approval(
    ?array $before, array $after, bool $resume, array $rootKeys, array $approvalKeys,
    ?int $now = null
): bool {
    extended_review_registry_manifest($before, $after, $rootKeys, $now ?? time(), $resume);

    extended_verify_signed_manifest(
        extended_registry_approval_claims($after), $after['approval'], $approvalKeys, array_keys($approvalKeys)
    );
    return true;
}

/** Verify the publisher and metadata before displaying a proposal. */
function extended_review_registry_manifest(
    ?array $before, array $after, array $rootKeys, int $now, bool $allowExpired = false
): array {
    if ($before !== null && $after['policy'] !== $before['policy']) {
        throw new RuntimeException('Registry policy changes require separate authorization');
    }

    $manifest = extended_verify_signed_manifest(
        $after['manifest'], $after['signature'], $rootKeys, array_keys($rootKeys)
    );
    extended_validate_registry_manifest($manifest, $now, $allowExpired);
    if ($manifest['registry_id'] !== $after['registry'] || $manifest['sequence'] !== $after['sequence']) {
        throw new RuntimeException('Signed registry identity or sequence differs from staged evidence');
    }

    if ($before !== null && ($after['sequence'] < $before['sequence'] ||
        ($after['sequence'] === $before['sequence'] && $after['manifest'] !== $before['manifest']))) {
        throw new RuntimeException('Registry sequence rollback or equivocation');
    }
    return $manifest;
}

/** Exact bytes to present for review and sign with the independent approval key. */
function extended_registry_approval_claims(array $after): string
{
    return json_encode([
        'schema_version' => 1,
        'purpose' => 'composr-registry-approval',
        'deployment' => $after['deployment'],
        'registry' => $after['registry'],
        'generation' => $after['generation'],
        'prior_digest' => bin2hex($after['prior_digest']),
        'approval_id' => $after['approval_id'],
        'manifest_digest' => hash('sha256', $after['manifest']),
        'signature_digest' => hash('sha256', $after['signature']),
        'policy_digest' => hash('sha256', $after['policy']),
    ], JSON_THROW_ON_ERROR);
}
