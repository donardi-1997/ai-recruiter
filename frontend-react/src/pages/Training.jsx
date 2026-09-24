// eslint-disable-next-line no-unused-vars
import React from "react";
import { useSession } from "../context/SessionContext";

function Training() {
  const { principal } = useSession();
  const name = principal?.profile?.first_name || "equipo";

  return (
    <div className="page training-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">Aprendizaje interno</span>
          <h1>Capacitación</h1>
          <p>Hola, {name}. Este será tu espacio de inducción y formación en ASIATI.</p>
        </div>
      </header>

      <section className="panel training-coming-soon">
        <span className="training-mark" aria-hidden="true">▶</span>
        <div>
          <span className="eyebrow">Siguiente fase</span>
          <h2>Inducción ASIATI</h2>
          <p>Los cursos, videos, progreso y evaluaciones se publicarán aquí. La estructura de permisos ya está preparada para mostrar únicamente la capacitación asignada a cada empleado.</p>
        </div>
      </section>
    </div>
  );
}

export default Training;
