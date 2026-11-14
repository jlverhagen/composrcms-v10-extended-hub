<?php
declare(strict_types=1);

/**
 * Encode an already validated generation. Policy and approval are exact
 * serialized evidence; the caller must validate their meaning before storage.
 * Fixed field order and byte lengths bind wire bytes without JSON re-encoding.
 */
function extended_registry_generation_evidence(
    string $deployment, string $registry, int $generation, int $sequence,
    string $priorDigest, string $approvalId, string $manifest, string $signature,
    string $policy, string $approval
): string {
    foreach ([$deployment, $registry, $approvalId] as $id) {
        if (!preg_match('/^[a-z0-9][a-z0-9_-]{0,63}$/D', $id)) {
            throw new InvalidArgumentException('Invalid registry state identity');
        }
    }
    if ($generation < 0 || $sequence < 0 || strlen($priorDigest) !== 32 ||
        strlen($manifest) > 2097152 || strlen($signature) > 4096 ||
        strlen($policy) > 2097152 || strlen($approval) > 2097152) {
        throw new InvalidArgumentException('Invalid registry generation evidence');
    }

    $evidence = "composr-registry-generation-v1\0";
    foreach ([$deployment, $registry, (string)$generation, (string)$sequence,
        $priorDigest, $approvalId, $manifest, $signature, $policy, $approval] as $field) {
        $evidence .= pack('N', strlen($field)) . $field;
    }
    return $evidence;
}

/** Decode the complete v1 evidence record for reconciliation. */
function extended_decode_registry_generation_evidence(string $evidence): array
{
    $prefix = "composr-registry-generation-v1\0";
    if (!str_starts_with($evidence, $prefix)) {
        throw new InvalidArgumentException('Unsupported registry evidence format');
    }
    $offset = strlen($prefix);
    $fields = [];
    foreach (['deployment', 'registry', 'generation', 'sequence', 'prior_digest',
        'approval_id', 'manifest', 'signature', 'policy', 'approval'] as $name) {
        if (strlen($evidence) - $offset < 4) {
            throw new InvalidArgumentException('Truncated registry evidence length');
        }
        $length = unpack('N', $evidence, $offset)[1];
        $offset += 4;
        if ($length > strlen($evidence) - $offset) {
            throw new InvalidArgumentException('Truncated registry evidence field');
        }
        $fields[$name] = substr($evidence, $offset, $length);
        $offset += $length;
    }
    $fields['generation'] = (int)$fields['generation'];
    $fields['sequence'] = (int)$fields['sequence'];
    if (extended_registry_generation_evidence(...array_values($fields)) !== $evidence) {
        throw new InvalidArgumentException('Noncanonical registry evidence');
    }
    return $fields;
}

/** Internal store for the operator. Signature and independent-record checks belong to the caller. */
final class ExtendedRegistryStore
{
    public function __construct(private PDO $db, private string $deployment, private string $registry)
    {
        if ($db->getAttribute(PDO::ATTR_DRIVER_NAME) !== 'mysql' ||
            $db->getAttribute(PDO::ATTR_ERRMODE) !== PDO::ERRMODE_EXCEPTION ||
            $db->getAttribute(PDO::ATTR_EMULATE_PREPARES)) {
            throw new InvalidArgumentException('Registry store requires PDO MySQL with native prepares and exceptions');
        }
    }

    private function query(string $sql, array $arguments = []): PDOStatement
    {
        $stmt = $this->db->prepare($sql);
        $stmt->execute(array_merge([$this->deployment, $this->registry], $arguments));
        return $stmt;
    }

    private function transaction(callable $operation): mixed
    {
        $this->db->beginTransaction();
        try {
            $result = $operation();
            $this->db->commit();
            return $result;
        } catch (Throwable $error) {
            if ($this->db->inTransaction()) {
                $this->db->rollBack();
            }
            throw $error;
        }
    }

    public function head(): ?array
    {
        return $this->readHead(false);
    }

    private function readHead(bool $lock): ?array
    {
        $row = $this->query('SELECT generation, state_digest FROM extended_registry_heads
            WHERE deployment_id = ? AND registry_id = ?' . ($lock ? ' FOR UPDATE' : ''))->fetch(PDO::FETCH_ASSOC);
        return $row === false ? null : [(int)$row['generation'], $row['state_digest']];
    }

    public function evidence(int $generation, string $digest): ?string
    {
        $bytes = $this->query('SELECT evidence FROM extended_registry_generations
            WHERE deployment_id = ? AND registry_id = ? AND generation = ? AND state_digest = ?',
            [$generation, $digest])->fetchColumn();
        if ($bytes === false) {
            return null;
        }
        if (!hash_equals($digest, hash('sha256', $bytes, true))) {
            throw new RuntimeException('Stored registry evidence digest mismatch');
        }
        return $bytes;
    }

    /**
     * Stage evidence with an expected head. A null head is only for explicit
     * bootstrap; the operator must independently verify bootstrap eligibility.
     */
    public function stage(
        ?array $expected, int $sequence, string $approvalId, string $manifest,
        string $signature, string $policy, string $approval
    ): array {
        $generation = $expected === null ? 0 : $expected[0] + 1;
        $evidence = extended_registry_generation_evidence(
            $this->deployment, $this->registry, $generation, $sequence,
            $expected[1] ?? str_repeat("\0", 32), $approvalId, $manifest, $signature, $policy, $approval
        );
        $digest = hash('sha256', $evidence, true);
        return $this->transaction(function () use ($expected, $generation, $approvalId, $digest, $evidence) {
            $head = $this->readHead(true);
            $existing = $this->query('SELECT generation, state_digest, evidence FROM extended_registry_generations
                WHERE deployment_id = ? AND registry_id = ? AND approval_id = ?',
                [$approvalId])->fetch(PDO::FETCH_ASSOC);
            if ($existing !== false && ((int)$existing['generation'] !== $generation ||
                $existing['state_digest'] !== $digest || $existing['evidence'] !== $evidence)) {
                throw new RuntimeException('Registry approval identity already used');
            }
            $candidate = [$generation, $digest];
            if ($existing !== false && $head === $candidate) {
                return $candidate;
            }
            if ($head !== $expected) {
                throw new RuntimeException('Registry head changed since review');
            }
            if ($existing === false) {
                $this->query('INSERT INTO extended_registry_generations
                    (deployment_id, registry_id, generation, state_digest, approval_id, evidence)
                    VALUES (?, ?, ?, ?, ?, ?)', [$generation, $digest, $approvalId, $evidence]);
            }
            return $candidate;
        });
    }

    /** Call only after confirming the independent record names this candidate. */
    public function activate(?array $expected, array $candidate): void
    {
        $this->transaction(function () use ($expected, $candidate) {
            $head = $this->readHead(true);
            $evidence = $this->evidence($candidate[0], $candidate[1]);
            if ($candidate[0] !== ($expected === null ? 0 : $expected[0] + 1) || $evidence === null) {
                throw new RuntimeException('Registry candidate is missing or out of order');
            }
            $fields = extended_decode_registry_generation_evidence($evidence);
            if ($fields['deployment'] !== $this->deployment || $fields['registry'] !== $this->registry ||
                $fields['generation'] !== $candidate[0] ||
                $fields['prior_digest'] !== ($expected[1] ?? str_repeat("\0", 32))) {
                throw new RuntimeException('Registry candidate belongs to a different prior head');
            }
            if ($head === $candidate) {
                return;
            }
            if ($head !== $expected) {
                throw new RuntimeException('Registry head changed before activation');
            }
            if ($expected === null) {
                $this->query('INSERT INTO extended_registry_heads
                    (deployment_id, registry_id, generation, state_digest) VALUES (?, ?, ?, ?)', $candidate);
            } else {
                $stmt = $this->db->prepare('UPDATE extended_registry_heads SET generation = ?, state_digest = ?
                    WHERE deployment_id = ? AND registry_id = ?');
                $stmt->execute([...$candidate, $this->deployment, $this->registry]);
            }
        });
    }
}
