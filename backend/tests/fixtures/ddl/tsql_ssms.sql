-- Script como lo genera SQL Server Management Studio: GO en vez de ; y llaves CLUSTERED.
SET ANSI_NULLS ON
GO
CREATE TABLE [dbo].[Sucursales](
    [Id] [int] IDENTITY(1,1) NOT NULL,
    [Nombre] [nvarchar](80) NOT NULL,
 CONSTRAINT [PK_Sucursales] PRIMARY KEY CLUSTERED
(
    [Id] ASC
)
)
GO
CREATE TABLE [dbo].[Facturas](
    [Id] [int] NOT NULL,
    [SucursalId] [int] NOT NULL,
    [Total] [decimal](14, 2) NOT NULL,
 CONSTRAINT [PK_Facturas] PRIMARY KEY NONCLUSTERED ([Id] ASC),
 CONSTRAINT [FK_Facturas_Sucursales] FOREIGN KEY ([SucursalId]) REFERENCES [dbo].[Sucursales] ([Id])
)
GO
