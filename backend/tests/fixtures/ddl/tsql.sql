CREATE TABLE [dbo].[sucursales] (
    [id]     INT NOT NULL PRIMARY KEY,
    [nombre] NVARCHAR(80) NOT NULL
);

CREATE TABLE [dbo].[facturas] (
    [id]          INT NOT NULL,
    [sucursal_id] INT NOT NULL,
    [total]       DECIMAL(14, 2) NOT NULL,
    CONSTRAINT [pk_facturas] PRIMARY KEY ([id]),
    CONSTRAINT [fk_facturas_sucursales] FOREIGN KEY ([sucursal_id]) REFERENCES [dbo].[sucursales] ([id])
);

SELECT * FROM dbo.facturas;
