<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    exit(2);
}

require_once __DIR__ . '/registry-commit.php';
require_once __DIR__ . '/registry-approval.php';

function extended_registry_cli_head(string $generation, string $digest): array
{
    $number = filter_var($generation, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
    if ($number === false || !preg_match('/^[0-9a-f]{64}$/D', $digest)) {
        throw new InvalidArgumentException('Invalid generation or state digest');
    }
    return [$number, hex2bin($digest)];
}

function extended_registry_cli_read(string $path, int $limit): string
{
    $bytes = file_get_contents($path, false, null, 0, $limit + 1);
    if ($bytes === false || strlen($bytes) > $limit) {
        throw new RuntimeException('Cannot read bounded registry input');
    }
    return $bytes;
}

function extended_registry_cli_review(ExtendedRegistryStore $store, array $config, array $argv): void
{
    [, , $command, $approvalId, $manifestPath, $signaturePath, $policyPath] = $argv;
    $head = $store->head();
    $before = null;
    if ($head !== null) {
        $evidence = $store->evidence(...$head);
        if ($evidence === null) {
            throw new RuntimeException('Current registry evidence is missing');
        }
        $before = extended_decode_registry_generation_evidence($evidence);
    }
    $manifest = extended_registry_cli_read($manifestPath, 2097152);
    $signature = extended_registry_cli_read($signaturePath, 4096);
    $policy = extended_registry_cli_read($policyPath, 2097152);
    $decoded = json_decode($manifest, true, 512, JSON_THROW_ON_ERROR);
    $after = [
        'deployment' => $config['deployment'], 'registry' => $config['registry'],
        'generation' => $head === null ? 0 : $head[0] + 1,
        'sequence' => $decoded['sequence'] ?? null,
        'prior_digest' => $head[1] ?? str_repeat("\0", 32), 'approval_id' => $approvalId,
        'manifest' => $manifest, 'signature' => $signature, 'policy' => $policy,
    ];
    if (!preg_match('/^[a-z0-9][a-z0-9_-]{0,63}$/D', $approvalId)) {
        throw new InvalidArgumentException('Invalid registry approval ID');
    }
    $proposal = extended_review_registry_manifest($before, $after, $config['root_keys'], time());
    if ($command === 'review') {
        $keyId = json_decode($signature, true, 8, JSON_THROW_ON_ERROR)['key_id'];
        $publicKey = base64_decode($config['root_keys'][$keyId], true);
        $priorSources = $before === null ? [] : json_decode($before['manifest'], true, 512, JSON_THROW_ON_ERROR)['sources'];
        echo json_encode([
            'claims' => extended_registry_approval_claims($after),
            'publisher_fingerprint' => hash('sha256', $publicKey),
            'sequence' => $proposal['sequence'], 'expires_at' => $proposal['expires_at'],
            'prior_sources' => $priorSources, 'proposed_sources' => $proposal['sources'],
        ], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR), PHP_EOL;
        return;
    }
    $after['approval'] = extended_registry_cli_read($argv[7], 4096);
    extended_verify_registry_approval($before, $after, false, $config['root_keys'], $config['approval_keys']);
    $candidate = $store->stage($head, $after['sequence'], $approvalId, $manifest, $signature, $policy, $after['approval']);
    echo json_encode(['generation' => $candidate[0], 'state_digest' => bin2hex($candidate[1])], JSON_THROW_ON_ERROR), PHP_EOL;
}

try {
    $command = $argv[2] ?? '';
    if (!(($argc === 3 && $command === 'reconcile') || ($argc === 7 && $command === 'commit') || ($argc === 4 && $command === 'bootstrap') ||
        ($argc === 7 && $command === 'review') || ($argc === 8 && $command === 'stage'))) {
        throw new InvalidArgumentException(
            'Usage: php commit-registry.php CONFIG {review ID MANIFEST SIGNATURE POLICY | stage ID MANIFEST SIGNATURE POLICY APPROVAL | reconcile | bootstrap DIGEST | commit PRIOR_GENERATION PRIOR_DIGEST GENERATION DIGEST}'
        );
    }
    $path = $argv[1];
    extended_registry_check_directory(dirname($path));
    extended_registry_check_existing_file($path);
    $mode = fileperms($path);
    if ($mode === false || ($mode & 0077) !== 0) {
        throw new RuntimeException('Registry operator configuration must be private');
    }
    $bytes = file_get_contents($path, false, null, 0, 65537);
    if ($bytes === false || strlen($bytes) > 65536) {
        throw new RuntimeException('Cannot read operator configuration');
    }
    $config = json_decode($bytes, true, 16, JSON_THROW_ON_ERROR);
    $record = $config['record'];
    extended_registry_check_directory(dirname($record));
    extended_registry_check_existing_file($record);
    extended_registry_check_existing_file($record . '.lock');

    $db = new PDO($config['dsn'], $config['user'], $config['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
    $store = new ExtendedRegistryStore($db, $config['deployment'], $config['registry']);
    if ($command === 'review' || $command === 'stage') {
        extended_registry_cli_review($store, $config, $argv);
        exit(0);
    }
    $operator = new ExtendedRegistryCommit(
        $store, $record,
        static fn(?array $before, array $after, bool $resume): bool => extended_verify_registry_approval(
            $before, $after, $resume, $config['root_keys'], $config['approval_keys']
        )
    );
    $head = match ($command) {
        'reconcile' => $operator->reconcile(),
        'bootstrap' => $operator->bootstrap(extended_registry_cli_head('0', $argv[3])),
        'commit' => $operator->commit(
            extended_registry_cli_head($argv[3], $argv[4]), extended_registry_cli_head($argv[5], $argv[6])
        ),
    };
    echo json_encode(['generation' => $head[0], 'state_digest' => bin2hex($head[1])], JSON_THROW_ON_ERROR), PHP_EOL;
} catch (PDOException $error) {
    fwrite(STDERR, 'Registry database operation failed' . PHP_EOL);
    exit(1);
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . PHP_EOL);
    exit(1);
}
