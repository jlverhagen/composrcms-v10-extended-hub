<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    exit(2);
}

function read_registry_receipt_input(string $path): string
{
    $bytes = @file_get_contents($path, false, null, 0, 2097153);
    if ($bytes === false || strlen($bytes) > 2097152) {
        throw new RuntimeException('Cannot read bounded review or receipt input');
    }
    return $bytes;
}

try {
    if ($argc !== 3) {
        throw new InvalidArgumentException('Usage: php check-registry-receipt.php REVIEW_JSON RECEIPT_JSON');
    }
    $reviewBytes = read_registry_receipt_input($argv[1]);
    $review = json_decode($reviewBytes, true, 64, JSON_THROW_ON_ERROR);
    $receipt = json_decode(read_registry_receipt_input($argv[2]), true, 16, JSON_THROW_ON_ERROR);
    $now = time();
    $claims = $review['claims'] ?? null;
    $expires = $review['expires_at'] ?? null;
    $confirmed = $receipt['confirmed_at'] ?? null;
    $member = $receipt['member_id'] ?? null;

    if (!is_string($claims) || !is_int($expires) || $expires <= $now ||
        !is_int($confirmed) || $confirmed < 1 || $confirmed > $now || $confirmed >= $expires ||
        !is_int($member) || $member < 1 ||
        ($receipt['review_sha256'] ?? null) !== hash('sha256', $reviewBytes) ||
        ($receipt['claims'] ?? null) !== $claims) {
        throw new RuntimeException('Receipt does not match the current review or its confirmation window');
    }
    $decoded = json_decode($claims, true, 16, JSON_THROW_ON_ERROR);
    if (($decoded['schema_version'] ?? null) !== 1 ||
        ($decoded['purpose'] ?? null) !== 'composr-registry-approval') {
        throw new RuntimeException('Invalid registry approval claims');
    }

    fwrite(STDERR, "Matching receipt for CMS member $member. Verify the reviewer independently before signing.\n");
    fwrite(STDOUT, $claims);
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . PHP_EOL);
    exit(1);
}
