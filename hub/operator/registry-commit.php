<?php
declare(strict_types=1);

require_once __DIR__ . '/registry-store.php';

/**
 * Coordinates a scoped store with a pre-provisioned operator record.
 * Use a dedicated, operator-owned directory and one record per store scope.
 * The verifier must authenticate the evidence and prior policy. On resume,
 * it must permit expiry while still verifying all other approval evidence.
 */
final class ExtendedRegistryCommit
{
    public function __construct(
        private ExtendedRegistryStore $store,
        private string $record,
        private Closure $verify
    ) {
    }

    private function locked(Closure $operation, bool $bootstrap = false): array
    {
        $lock = fopen($this->record . '.lock', 'c');
        if ($lock === false) {
            throw new RuntimeException('Cannot open registry commit lock');
        }
        try {
            if (!flock($lock, LOCK_EX)) {
                throw new RuntimeException('Cannot acquire registry commit lock');
            }
            clearstatcache(true, $this->record);
            if ($bootstrap && !file_exists($this->record) && !is_link($this->record)) {
                return $operation(null);
            }
            $bytes = @file_get_contents($this->record, false, null, 0, 1025);
            if ($bytes === false || strlen($bytes) > 1024) {
                throw new RuntimeException('Independent registry record unavailable');
            }
            $record = json_decode($bytes, true, 8, JSON_THROW_ON_ERROR);
            if (!is_array($record) || ($record['version'] ?? null) !== 1 ||
                !is_int($record['generation'] ?? null) || $record['generation'] < 0 ||
                !is_string($record['state_digest'] ?? null) ||
                !preg_match('/^[0-9a-f]{64}$/D', $record['state_digest'])) {
                throw new RuntimeException('Invalid independent registry record');
            }
            $head = [$record['generation'], hex2bin($record['state_digest'])];
            if ($this->recordFor($head) !== $record) {
                throw new RuntimeException('Independent registry record does not match stored evidence');
            }
            return $operation($head);
        } finally {
            fclose($lock);
        }
    }

    private function fields(array $head): array
    {
        $bytes = $this->store->evidence(...$head);
        if ($bytes === null) {
            throw new RuntimeException('Registry recovery required: generation evidence missing');
        }
        return extended_decode_registry_generation_evidence($bytes);
    }

    private function recordFor(array $head): array
    {
        $fields = $this->fields($head);
        return [
            'version' => 1,
            'deployment' => $fields['deployment'],
            'registry' => $fields['registry'],
            'generation' => $head[0],
            'sequence' => $fields['sequence'],
            'manifest_digest' => hash('sha256', $fields['manifest']),
            'state_digest' => bin2hex($head[1]),
        ];
    }

    private function publish(array $head): void
    {
        $bytes = json_encode($this->recordFor($head), JSON_THROW_ON_ERROR) . "\n";
        $directory = dirname($this->record);
        $dir = fopen($directory, 'r');
        if ($dir === false) {
            throw new RuntimeException('Cannot open independent registry directory');
        }
        $pending = $this->record . '.' . bin2hex(random_bytes(16));
        try {
            $file = fopen($pending, 'xb');
            if ($file === false) {
                throw new RuntimeException('Cannot create pending registry record');
            }
            try {
                if (!chmod($pending, 0640) || (is_file($this->record) && !chgrp($pending, filegroup($this->record))) ||
                    fwrite($file, $bytes) !== strlen($bytes) || !fflush($file) || !fsync($file)) {
                    throw new RuntimeException('Cannot persist pending registry record');
                }
            } finally {
                fclose($file);
            }
            if (!rename($pending, $this->record) || !fsync($dir)) {
                throw new RuntimeException('Cannot durably publish independent registry record');
            }
        } finally {
            fclose($dir);
            if (is_file($pending)) {
                unlink($pending);
            }
        }
    }

    public function bootstrap(array $candidate): array
    {
        return $this->locked(function (?array $independent) use ($candidate) {
            $head = $this->store->head();
            if ($candidate[0] !== 0 || ($independent !== null && $independent !== $candidate) ||
                ($head !== null && ($head !== $candidate || $independent !== $candidate))) {
                throw new RuntimeException('Registry bootstrap requires an unused deployment or an exact retry');
            }
            $fields = $this->fields($candidate);
            if ($fields['generation'] !== 0 || $fields['prior_digest'] !== str_repeat("\0", 32) ||
                ($this->verify)(null, $fields, $independent !== null) !== true) {
                throw new RuntimeException('Registry bootstrap evidence was rejected');
            }
            // Republishing the exact record also completes a previously interrupted directory sync.
            $this->publish($candidate);
            $this->store->activate(null, $candidate);
            return $candidate;
        }, true);
    }

    public function commit(array $expected, array $candidate): array
    {
        return $this->locked(function (array $independent) use ($expected, $candidate) {
            if ($independent === $candidate) {
                return $this->reconcileHead($independent);
            }
            if ($independent !== $expected || $this->store->head() !== $expected) {
                throw new RuntimeException('Registry head changed or requires reconciliation');
            }
            $this->verifySuccessor($expected, $candidate, false);
            $this->publish($candidate);
            $this->store->activate($expected, $candidate);
            return $candidate;
        });
    }

    public function reconcile(): array
    {
        return $this->locked(fn(array $head) => $this->reconcileHead($head));
    }

    private function reconcileHead(array $independent): array
    {
        $head = $this->store->head();
        if ($head !== $independent) {
            if ($head === null) {
                throw new RuntimeException('Registry recovery required: database head missing');
            }
            $this->verifySuccessor($head, $independent, true);
            // A prior publisher may have stopped after rename and before directory sync.
            $dir = fopen(dirname($this->record), 'r');
            if ($dir === false) {
                throw new RuntimeException('Cannot open independent registry directory');
            }
            try {
                if (!fsync($dir)) {
                    throw new RuntimeException('Cannot sync independent registry directory');
                }
            } finally {
                fclose($dir);
            }
            $this->store->activate($head, $independent);
        }
        return $independent;
    }

    private function verifySuccessor(array $prior, array $candidate, bool $resume): void
    {
        $before = $this->fields($prior);
        $after = $this->fields($candidate);
        if ($candidate[0] !== $prior[0] + 1 || $after['prior_digest'] !== $prior[1] ||
            $after['deployment'] !== $before['deployment'] || $after['registry'] !== $before['registry'] ||
            $after['generation'] !== $candidate[0] || $before['generation'] !== $prior[0] ||
            $after['sequence'] < $before['sequence'] ||
            ($after['sequence'] === $before['sequence'] && $after['manifest'] !== $before['manifest'])) {
            throw new RuntimeException('Registry candidate does not extend the approved head');
        }
        if (($this->verify)($before, $after, $resume) !== true) {
            throw new RuntimeException('Registry approval evidence was rejected');
        }
    }
}
