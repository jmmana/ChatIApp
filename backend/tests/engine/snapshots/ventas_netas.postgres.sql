SELECT DATE_TRUNC('MONTH', facturas.fecha) AS periodo, sucursales.nombre AS nombre, SUM(facturas.total) AS valor
FROM facturas
LEFT JOIN sucursales ON facturas.sucursal_id = sucursales.id
WHERE facturas.estado = 'PAGADA' AND facturas.fecha >= CAST('2025-01-01' AS DATE) AND facturas.fecha < CAST('2025-04-01' AS DATE)
GROUP BY DATE_TRUNC('MONTH', facturas.fecha), sucursales.nombre
ORDER BY periodo ASC, sucursales.nombre ASC
LIMIT 1000
