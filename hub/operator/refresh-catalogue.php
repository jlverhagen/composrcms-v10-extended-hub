<?php
// Run from a trusted, administrator-owned copy of the checkpoint.
if (PHP_SAPI !== 'cli' || $argc !== 4) {
    fwrite(STDERR, "Usage: php refresh-catalogue.php TRUSTED_CONFIG STATE_RECORD SOURCE_ID\n");
    exit(2);
}
$code = __DIR__ . '/../../cms/sources_custom/';
require_once $code . 'extended_catalogue_high_water.php';
require_once $code . 'extended_catalogue_snapshot.php';
require_once $code . 'extended_http_transport.php';

try {
    [, $configPath, $recordPath, $sourceId] = $argv;
    if (!preg_match('/^[a-z0-9][a-z0-9_-]{0,63}$/D', $sourceId)) {
        throw new RuntimeException('Invalid source ID');
    }
    $state = extended_read_catalogue_high_water($recordPath);
    if (!isset($state['sources'][$sourceId])) {
        throw new RuntimeException('Seed the source before refreshing it');
    }
    $config = json_decode(file_get_contents($configPath), true, 512, JSON_THROW_ON_ERROR);
    $source = $config['sources'][$sourceId] ?? null;
    if (!is_array($source) || ($source['enabled'] ?? null) !== true) {
        throw new RuntimeException('Source is not enabled in the operator configuration');
    }
    $root = dirname($recordPath);
    $downloads = [];
    try {
        $downloads[] = extended_transport_fetch($source['manifest_url'], $root);
        $downloads[] = extended_transport_fetch($source['signature_url'], $root, 4096);
        $snapshot = extended_stage_signed_catalogue_snapshot(
            $downloads[0], $downloads[1], $source['trusted_keys'], $source['allowed_key_ids'], $sourceId, $root
        );
        $group = filegroup($recordPath);
        foreach ([$snapshot['manifest_path'], $snapshot['signature_path']] as $file) {
            if (!chgrp($file, $group) || !chmod($file, 0640)) {
                throw new RuntimeException('Cannot grant catalogue reader access to the snapshot');
            }
        }
        $dir = dirname($snapshot['manifest_path']);
        if (!chgrp($dir, $group) || !chmod($dir, 0750)) {
            throw new RuntimeException('Cannot grant catalogue reader access to the snapshot directory');
        }
        // Publish the pointer only after the verified pair is readable.
        $approved = extended_approve_catalogue_high_water(
            $recordPath, $sourceId, file_get_contents($snapshot['manifest_path']),
            file_get_contents($snapshot['signature_path']), $source['trusted_keys'], $source['allowed_key_ids']
        );
        echo json_encode($approved, JSON_THROW_ON_ERROR), PHP_EOL;
    } finally {
        foreach ($downloads as $file) @unlink($file);
    }
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . PHP_EOL);
    exit(1);
}
