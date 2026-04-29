# DELFOS — Guía para el Usuario

**Versión:** 1.0 · Abril 2026

---

## ¿Qué es DELFOS?

DELFOS es una plataforma de salud que reúne toda tu información médica y de bienestar en un solo lugar. Su objetivo es ayudar a **prevenir y detectar a tiempo enfermedades crónicas**, especialmente la diabetes tipo 2, usando tecnología e inteligencia artificial.

En lugar de tener tus datos dispersos en diferentes aplicaciones y registros, DELFOS los consolida para que tú y tu equipo de salud tengan una visión completa de tu estado.

---

## ¿Para qué sirve?

| Función | ¿Qué hace por ti? |
|---------|-------------------|
| **Evaluación de riesgo** | Responde un cuestionario sencillo (FINDRISK) y obtén tu nivel de riesgo de desarrollar diabetes |
| **Seguimiento nutricional** | Registra tus comidas y conoce las calorías, proteínas, carbohidratos y grasas que consumes |
| **Actividad física** | Visualiza tus pasos diarios, frecuencia cardíaca y horas de sueño |
| **Alertas automáticas** | Recibe avisos si alguno de tus indicadores está fuera de rango (peso, presión arterial, inactividad) |
| **Informes de salud** | Tu profesional de salud puede generar reportes detallados sobre tu evolución |
| **Visitas de campo** | Si un profesional te visita en casa, esos datos también quedan registrados |

---

## ¿Qué es Viaggio?

**Viaggio** es la aplicación móvil complementaria a DELFOS. A través de un chatbot por WhatsApp, te permite registrar información de salud de forma fácil y rápida desde tu celular.

### ¿Qué datos se recopilan con Viaggio?

| Tipo de dato | Descripción | ¿Para qué se usa? |
|-------------|-------------|-------------------|
| **Perfil del paciente** | Nombre, edad, sexo, municipio, peso, talla, IMC, perímetro abdominal | Conocer tu perfil de salud general y calcular indicadores de riesgo |
| **Alimentación** | Comidas registradas con foto, calorías, proteínas, carbohidratos, grasas, azúcar y fibra | Evaluar tu dieta, detectar patrones alimenticios y sugerir mejoras |
| **Conversaciones** | Historial de mensajes con el chatbot nutricional | Dar seguimiento a tus consultas y recomendaciones personalizadas |
| **Actividad física** | Pasos diarios, tipo de actividad, frecuencia cardíaca y minutos de sueño | Monitorear tu nivel de actividad y descanso para una visión integral de tu salud |

### ¿Cómo funciona?

1. **Te registras** en la aplicación con tu número de teléfono o correo electrónico
2. **Interactúas** con el chatbot por WhatsApp: le envías fotos de tus comidas, le cuentas qué actividad física hiciste, etc.
3. **La información se sincroniza** automáticamente con DELFOS
4. **Tu equipo de salud** puede ver todo consolidado en tu perfil y tomar decisiones informadas

### ¿Cómo se accede?

- **Por teléfono (OTP):** Recibes un código por SMS para verificar tu identidad — ideal si no tienes correo electrónico
- **Por correo electrónico:** Registro tradicional con email y contraseña

---

## ¿Quiénes participan en el proyecto?

### Asociados y aliados

| Entidad | Rol en el proyecto |
|---------|-------------------|
| **Equipo DELFOS** | Desarrollo de la plataforma, inteligencia artificial y análisis de datos |
| **Viaggio** | Aplicación móvil de nutrición y seguimiento por WhatsApp |
| **Huella** | Plataforma de visitas domiciliarias y trabajo de campo |
| **Profesionales de salud** | Médicos, nutricionistas y trabajadores de campo que usan la información para tu cuidado |
| **Instituciones de salud** | Hospitales y clínicas que integran sus sistemas con DELFOS |

---

## ¿Mis datos están seguros?

Sí. DELFOS implementa múltiples capas de protección:

- 🔒 **Cifrado de datos:** Tu información se almacena cifrada en servidores seguros
- 👤 **Acceso controlado:** Solo las personas autorizadas pueden ver tus datos
- 🏥 **Estándar internacional:** Usamos HL7 FHIR, el estándar mundial para datos de salud
- 🔐 **Verificación de identidad:** Cada acceso requiere autenticación (contraseña o código SMS)
- 🧪 **Datos de investigación anonimizados:** Si tus datos se usan para investigación, se eliminan todos los datos personales

---

## ¿Qué indicadores de salud se monitorean?

DELFOS rastrea más de 20 variables clínicas organizadas por categoría:

### Antropometría
- Peso, talla, IMC (índice de masa corporal)
- Perímetro abdominal
- Peso ideal (rango mínimo y máximo)

### Riesgo metabólico
- Puntaje FINDRISK (escala 0-26)
- Clasificación de riesgo de diabetes
- Antecedentes familiares de diabetes
- Presencia de hipertensión, dislipidemia u otras condiciones crónicas

### Estilo de vida
- Nivel de actividad física
- Tipo de dieta
- Consumo de frutas y verduras
- Alergias e intolerancias alimentarias

### Nutrición diaria (vía Viaggio)
- Calorías consumidas por comida
- Distribución de macronutrientes (proteínas, carbohidratos, grasas)
- Contenido de azúcar y fibra dietaria
- Riesgo de pico de glucosa por alimento

---

## Alertas automáticas

El sistema genera alertas cuando detecta valores fuera de rango:

| Alerta | Condición | ¿Qué significa? |
|--------|-----------|-----------------|
| ⚠️ Obesidad | IMC mayor a 30 | Tu peso puede estar afectando tu salud |
| ⚠️ Hipertensión | Presión arterial ≥ 130/85 | Tu presión arterial está elevada |
| ⚠️ Riesgo alto de diabetes | FINDRISK ≥ 15 puntos | Tienes factores de riesgo importantes |
| ⚠️ Inactividad | Sin registros por más de 14 días | Es importante mantener el seguimiento activo |

---

## Preguntas frecuentes

**¿Necesito descargar alguna aplicación?**
Para registrar comidas y actividad física usas Viaggio a través de WhatsApp. Para ver tu perfil completo, tu equipo de salud accede a DELFOS desde un navegador web.

**¿Puedo ver mis propios datos?**
Sí, con tu cuenta puedes acceder a tu perfil, ver tus evaluaciones FINDRISK y revisar tu historial.

**¿Qué pasa si no tengo correo electrónico?**
Puedes registrarte con tu número de teléfono celular. Recibirás un código SMS para acceder.

**¿Mis datos se comparten con terceros?**
Tus datos personales solo son visibles para tu equipo de salud autorizado. Para investigación científica, se usan datos completamente anonimizados.

**¿Qué hago si tengo una alerta?**
Las alertas son informativas. Consulta con tu profesional de salud para recibir orientación personalizada.

---

*Este documento es una guía informativa para los usuarios del proyecto DELFOS. Para información técnica, consulte la documentación del sistema.*


# Información sobre el aplicativo Biomarcadores, si preguntan el aplicación movil

Qué es Biomarcadores
Biomarcadores es una aplicación de seguimiento personal de salud y bienestar que te ayuda a visualizar datos como actividad física, ritmo cardíaco estimado y otros indicadores relacionados con tus hábitos y mediciones dentro de la app.

Objetivo de la app
El objetivo de Biomarcadores es darte una referencia orientativa sobre tu estado y evolución a partir de datos del dispositivo, sensores de salud y mediciones realizadas en la app.
No sustituye un diagnóstico médico ni reemplaza equipos clínicos o la valoración de un profesional de la salud.

Para qué sirve

Consultar tu historial de mediciones.
Visualizar datos de actividad y salud sincronizados desde tu dispositivo.
Estimar ciertos indicadores mediante la cámara y señales del teléfono.
Apoyarte en el seguimiento de hábitos y tendencias personales.
Centralizar información de salud en un solo lugar para consulta personal.
Qué puede hacer el usuario

Iniciar sesión y gestionar su perfil.
Realizar mediciones dentro de la app.
Consultar el historial de resultados guardados.
Sincronizar información de salud desde plataformas compatibles como Health Connect, Samsung Health o Apple Health, según el dispositivo.
Revisar datos de actividad como pasos y otras señales disponibles.
Consultar ayuda y orientación de uso.
Cerrar sesión.
Borrar datos locales del dispositivo.
Solicitar la eliminación de su cuenta y de sus datos.
Qué tipo de información puede usar la app
Según el dispositivo y los permisos otorgados, la app puede usar:

Cámara
Actividad física
Pasos
Frecuencia cardíaca
Sueño
Datos de plataformas de salud compatibles
Importante para el usuario

Los resultados son orientativos.
Algunas funciones dependen de permisos del sistema.
Algunas integraciones pueden variar según Android, iPhone, Samsung Health, Health Connect o Apple Health.
La precisión puede cambiar según iluminación, movimiento, posición del dedo y modelo del dispositivo.
Mensaje corto tipo ficha o onboarding
Biomarcadores te ayuda a seguir tus mediciones, actividad y tendencias de salud desde tu celular, integrando datos del dispositivo y plataformas compatibles. Sus resultados son orientativos y no reemplazan la evaluación de un profesional de la salud.