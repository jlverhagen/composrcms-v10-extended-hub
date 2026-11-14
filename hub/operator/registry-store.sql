CREATE TABLE extended_registry_generations (
    deployment_id VARBINARY(64) NOT NULL,
    registry_id VARBINARY(64) NOT NULL,
    generation BIGINT UNSIGNED NOT NULL,
    state_digest BINARY(32) NOT NULL,
    approval_id VARBINARY(64) NOT NULL,
    evidence MEDIUMBLOB NOT NULL,
    PRIMARY KEY (deployment_id, registry_id, generation, state_digest),
    UNIQUE KEY approval (deployment_id, registry_id, approval_id)
) ENGINE=InnoDB;

CREATE TABLE extended_registry_heads (
    deployment_id VARBINARY(64) NOT NULL,
    registry_id VARBINARY(64) NOT NULL,
    generation BIGINT UNSIGNED NOT NULL,
    state_digest BINARY(32) NOT NULL,
    PRIMARY KEY (deployment_id, registry_id),
    FOREIGN KEY (deployment_id, registry_id, generation, state_digest)
        REFERENCES extended_registry_generations (deployment_id, registry_id, generation, state_digest)
) ENGINE=InnoDB;
