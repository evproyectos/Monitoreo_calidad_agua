import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { descartarPrecarga, pedir } from "./api.js";
import App from "./App.jsx";
import InicioSesion, { Marca } from "./componentes/InicioSesion.jsx";

// RNF-001: la vista general viene en el mismo archivo que el inicio de sesión (son unos 10 KB
// comprimidos, y así quien ya tiene sesión no espera otra vuelta a la red); lo demás (gráficos,
// detalle, usuarios, gestión de alertas, cuenta) se carga cuando hace falta.
const Cuenta = lazy(() => import("./componentes/Cuenta.jsx"));
const cargando = <div className="pantalla-sesion"><p className="vacio">Cargando…</p></div>;

// Decide qué se ve: la pantalla de inicio de sesión (CU-00), el cambio obligatorio de la
// contraseña temporal o el dashboard con los permisos del rol.
export default function Sesion() {
  const [s, setS] = useState({ cargando: true, datos: null });

  const cargar = useCallback(async () => {
    try {
      const datos = await pedir("/api/sesion");
      if (datos.usuario.debe_cambiar) descartarPrecarga();
      setS({ cargando: false, datos });
    } catch (e) {
      descartarPrecarga();
      setS({ cargando: false, datos: null, sinServicio: !(e.status < 500) });
    }
  }, []);

  useEffect(() => {
    cargar();
    const vencida = () => setS((x) => (x.datos ? { cargando: false, datos: null, vencida: true } : x));
    window.addEventListener("sesion:vencida", vencida);
    window.addEventListener("sesion:cambiar", cargar);
    return () => {
      window.removeEventListener("sesion:vencida", vencida);
      window.removeEventListener("sesion:cambiar", cargar);
    };
  }, [cargar]);

  const salir = async () => {
    try { await pedir("/api/sesion", { metodo: "DELETE" }); } catch { /* ya estaba cerrada */ }
    window.location.hash = "#/general";
    setS({ cargando: false, datos: null });
  };

  if (s.cargando) return cargando;

  if (!s.datos) {
    return <InicioSesion vencida={s.vencida} sinServicio={s.sinServicio} onReintentar={cargar}
                         onEntrar={(datos) => setS({ cargando: false, datos })} />;
  }

  if (s.datos.usuario.debe_cambiar) {
    return (
      <div className="pantalla-sesion">
        <div className="tarjeta-sesion">
          <Marca />
          <Suspense fallback={<p className="vacio">Cargando…</p>}>
            <Cuenta obligatoria usuario={s.datos.usuario} onListo={(datos) => setS({ cargando: false, datos })}
                    onSalir={salir} />
          </Suspense>
        </div>
      </div>
    );
  }

  return <App sesion={s.datos} onSalir={salir} onActualizar={(datos) => setS({ cargando: false, datos })} />;
}
