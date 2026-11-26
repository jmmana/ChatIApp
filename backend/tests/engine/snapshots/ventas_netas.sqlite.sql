SELECT STRFTIME('%Y-%m-01', facturas.fecha) AS periodo, sucursales.nombre AS nombre, SUM(facturas.total) AS valor
FROM facturas
LEFT JOIN sucursales ON facturas.sucursal_id = sucursales.id
WHERE facturas.estado = 'PAGADA' AND facturas.fecha >= '2025-01-01' AND facturas.fecha < '2025-04-01'
GROUP BY STRFTIME('%Y-%m-01', facturas.fecha), sucursales.nombre
ORDER BY periodo ASC, sucursales.nombre ASC
LIMIT 1000
