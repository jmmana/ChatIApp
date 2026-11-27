import {
  Bot,
  Database,
  FlaskConical,
  MessageSquare,
  Plug,
  ScrollText,
  Table2,
  Users,
  type LucideIcon,
} from "lucide-react";

export interface AppRoute {
  path: string;
  title: string;
  description: string;
  icon: LucideIcon;
  /** Solo la ven los administradores; el servidor sigue imponiendo el permiso. */
  adminOnly?: boolean;
}

export const appRoutes: AppRoute[] = [
  {
    path: "/chat",
    title: "Chat",
    description: "Aquí podrás hacer preguntas sobre tus datos en lenguaje natural.",
    icon: MessageSquare,
  },
  {
    path: "/modelo-semantico",
    title: "Modelo semántico",
    description: "Aquí podrás describir tablas, métricas y reglas de seguridad.",
    icon: Table2,
    adminOnly: true,
  },
  {
    path: "/proveedores-ia",
    title: "Proveedores de IA",
    description: "Aquí podrás configurar y probar los proveedores de IA.",
    icon: Bot,
    adminOnly: true,
  },
  {
    path: "/fuentes-de-datos",
    title: "Fuentes de datos",
    description: "Aquí podrás conectar y revisar las bases de datos.",
    icon: Database,
    adminOnly: true,
  },
  {
    path: "/integraciones",
    title: "Integraciones",
    description: "Aquí podrás administrar las API keys de las apps que integran ChatIApp.",
    icon: Plug,
    adminOnly: true,
  },
  {
    path: "/usuarios",
    title: "Usuarios",
    description: "Aquí podrás administrar usuarios, su rol por fuente y sus atributos.",
    icon: Users,
    adminOnly: true,
  },
  {
    path: "/auditoria",
    title: "Auditoría",
    description: "Aquí podrás revisar quién preguntó qué y qué SQL se ejecutó.",
    icon: ScrollText,
    adminOnly: true,
  },
  {
    path: "/evaluacion",
    title: "Evaluación",
    description: "Aquí podrás comparar modelos con el set de preguntas de referencia.",
    icon: FlaskConical,
    adminOnly: true,
  },
];
