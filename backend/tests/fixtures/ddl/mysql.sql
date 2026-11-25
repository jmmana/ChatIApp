CREATE TABLE `clientes` (
    `id`     INT NOT NULL PRIMARY KEY COMMENT 'Identificador del cliente',
    `nombre` VARCHAR(120) NOT NULL COMMENT 'Nombre completo',
    `email`  VARCHAR(160),
    UNIQUE KEY `uq_email` (`email`)
) COMMENT='Clientes de la tienda';

CREATE TABLE `tienda`.`pedidos` (
    `id`         INT NOT NULL,
    `cliente_id` INT NOT NULL,
    `total`      DECIMAL(10,2) NOT NULL COMMENT 'Total del pedido',
    PRIMARY KEY (`id`),
    CONSTRAINT `fk_pedidos_clientes` FOREIGN KEY (`cliente_id`) REFERENCES `clientes` (`id`)
);

CREATE TABLE `tienda`.`pedido_lineas` (
    `pedido_id` INT NOT NULL,
    `linea`     INT NOT NULL,
    PRIMARY KEY (`pedido_id`, `linea`),
    FOREIGN KEY (`pedido_id`) REFERENCES `tienda`.`pedidos` (`id`)
);
