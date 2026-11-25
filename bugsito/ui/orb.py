"""
Interfaz gráfica de Bugsito: Bola de energía (Arc Reactor / Plasma Orb) en GTK3 + Cairo.
Soporta Wayland mediante GtkLayerShell (capa OVERLAY anclada en la esquina inferior derecha)
y fallback automático a ventana flotante transparente en X11 u otros escritorios Linux.
"""

import math
import os
import signal
import threading
import time
from typing import Any

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

HAS_LAYER_SHELL = False
try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell

    HAS_LAYER_SHELL = True
except Exception:
    HAS_LAYER_SHELL = False

from bugsito.audio.stt import iniciar_grabacion_ffmpeg, transcribir_audio
from bugsito.audio.tts import hablar
from bugsito.config import (
    AUDIO_FILE,
    PIDFILE,
    STOPFILE,
    cargar_config,
    leer_colores_tema,
)
from bugsito.orchestrator.router import BugsitoOrchestrator


class BugsitoWindow(Gtk.Window):
    def __init__(self, cfg: dict[str, Any]):
        super().__init__()
        self.cfg = cfg
        self.orchestrator = BugsitoOrchestrator(cfg)

        ui_cfg = cfg.get("ui", {})
        width = int(ui_cfg.get("width", 260))
        height = int(ui_cfg.get("height", 260))
        margin_bottom = int(ui_cfg.get("margin_bottom", 55))
        margin_right = int(ui_cfg.get("margin_right", 35))
        self.font_family = ui_cfg.get("font_family", "JetBrainsMono Nerd Font")
        self.assistant_name = cfg.get("general", {}).get("name", "Bugsito")

        # Inicialización Wayland GtkLayerShell o Fallback flotante X11/estándar
        if HAS_LAYER_SHELL and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, bool(ui_cfg.get("anchor_bottom", True)))
            GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, bool(ui_cfg.get("anchor_right", True)))
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, margin_bottom)
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, margin_right)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
        else:
            self.set_keep_above(True)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
            display = Gdk.Display.get_default()
            if display:
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                if monitor:
                    geom = monitor.get_geometry()
                    self.move(
                        geom.x + geom.width - width - margin_right,
                        geom.y + geom.height - height - margin_bottom,
                    )

        # Configuración de transparencia y tamaño
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_size_request(width, height)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        # Colores dinámicos (integrados con ~/dotfiles/tema/tema.conf o config.toml)
        colores = leer_colores_tema(cfg)
        self.color_acento = colores["accent"]
        self.color_secundario = colores["secondary"]
        self.color_info = colores["info"]

        # Estados: RECORDING -> PROCESSING -> SPEAKING -> CLOSING
        self.state = "RECORDING"
        self.phase = 0.0
        self.alpha = 0.0
        self.target_alpha = 1.0
        self.subtitle = "● Escuchando... [Espacio]"
        self.response_text = ""
        self.recorder_proc = None

        self.draw_area = Gtk.DrawingArea()
        self.draw_area.connect("draw", self.on_draw)
        self.draw_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.draw_area.connect("button-press-event", self.on_button_press)
        self.add(self.draw_area)

        self.connect("key-press-event", self.on_key_press)
        self.connect("destroy", self.on_destroy)

        # Iniciar grabación de micrófono
        self.recorder_proc = iniciar_grabacion_ffmpeg()
        if not self.recorder_proc:
            self.subtitle = "Error de micrófono"

        GLib.timeout_add(33, self.on_tick)
        GLib.timeout_add(100, self.verificar_stopfile)

    def terminar_grabacion_y_procesar(self) -> None:
        if self.state != "RECORDING":
            return
        self.state = "PROCESSING"
        self.subtitle = "◌ Procesando orden..."

        if self.recorder_proc:
            try:
                self.recorder_proc.terminate()
                self.recorder_proc.wait(timeout=1.5)
            except Exception:
                try:
                    self.recorder_proc.kill()
                except Exception:
                    pass
            self.recorder_proc = None

        threading.Thread(target=self._hilo_proceso_y_respuesta, daemon=True).start()

    def _hilo_proceso_y_respuesta(self) -> None:
        time.sleep(0.1)
        if not AUDIO_FILE.is_file() or AUDIO_FILE.stat().st_size < 1000:
            self._actualizar_estado_habla("No se detectó audio del micrófono.")
            return

        texto_limpio = transcribir_audio(self.cfg)
        if not texto_limpio or len(texto_limpio) < 2:
            self._actualizar_estado_habla("No entendí la orden, por favor intenta de nuevo.")
            return

        print(f"[{self.assistant_name}] Reconocido: {texto_limpio}")
        self._actualizar_subtitulo(f'"{texto_limpio}"')

        respuesta_voz = self.orchestrator.procesar(texto_limpio)
        self._actualizar_estado_habla(respuesta_voz)

    def _actualizar_subtitulo(self, texto: str) -> None:
        def _cb():
            self.subtitle = texto
            self.draw_area.queue_draw()
            return False

        GLib.idle_add(_cb)

    def _actualizar_estado_habla(self, respuesta: str) -> None:
        def _cb():
            self.state = "SPEAKING"
            self.response_text = respuesta
            if len(respuesta) > 45:
                self.subtitle = f"🔊 {self.assistant_name}: {respuesta[:45]}..."
            else:
                self.subtitle = f"🔊 {respuesta}"
            self.draw_area.queue_draw()
            return False

        GLib.idle_add(_cb)

        hablar(respuesta, self.cfg)

        time.sleep(0.4)

        def _cerrar():
            self.state = "CLOSING"
            self.target_alpha = 0.0
            return False

        GLib.idle_add(_cerrar)

    def verificar_stopfile(self) -> bool:
        if STOPFILE.exists():
            try:
                STOPFILE.unlink()
            except Exception:
                pass
            if self.state == "RECORDING":
                self.terminar_grabacion_y_procesar()
        return True

    def on_key_press(self, widget, event) -> bool:
        keyval = event.keyval
        if keyval in (Gdk.KEY_space, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self.state == "RECORDING":
                self.terminar_grabacion_y_procesar()
                return True
        elif keyval == Gdk.KEY_Escape:
            self.cerrar_inmediato()
            return True
        return False

    def on_button_press(self, widget, event) -> bool:
        if self.state == "RECORDING":
            self.terminar_grabacion_y_procesar()
            return True
        if self.state in ("SPEAKING", "PROCESSING"):
            self.cerrar_inmediato()
            return True
        return False

    def on_tick(self) -> bool:
        self.phase += 0.06
        if self.alpha < self.target_alpha:
            self.alpha = min(self.target_alpha, self.alpha + 0.12)
        elif self.alpha > self.target_alpha:
            self.alpha = max(self.target_alpha, self.alpha - 0.15)
            if self.alpha <= 0.01:
                self.destroy()
                return False
        self.draw_area.queue_draw()
        return True

    def on_draw(self, widget, cr) -> None:
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        cx = w / 2.0
        cy = h / 2.0 - 15.0

        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)

        if self.alpha <= 0.001:
            return

        alpha = self.alpha
        t = self.phase

        if self.state == "RECORDING":
            r_c, g_c, b_c = self.color_info
            pulse = 0.55 + 0.35 * math.sin(t * 4.0)
            speed = 1.6
        elif self.state == "PROCESSING":
            r_c, g_c, b_c = (0.95, 0.75, 0.25)
            pulse = 0.65 + 0.30 * math.sin(t * 8.0)
            speed = 3.5
        elif self.state == "SPEAKING":
            r_c, g_c, b_c = self.color_secundario
            pulse = 0.50 + 0.45 * math.sin(t * 6.5)
            speed = 2.0
        else:
            r_c, g_c, b_c = self.color_acento
            pulse = 0.5
            speed = 1.0

        # 1. Aura de Resplandor Exterior (Glow)
        rad_glow = cairo.RadialGradient(cx, cy, 15, cx, cy, 105)
        rad_glow.add_color_stop_rgba(0.0, r_c, g_c, b_c, 0.40 * alpha * pulse)
        rad_glow.add_color_stop_rgba(0.5, r_c * 0.7, g_c * 0.7, b_c * 0.9, 0.18 * alpha * pulse)
        rad_glow.add_color_stop_rgba(1.0, 0.0, 0.0, 0.0, 0.0)
        cr.arc(cx, cy, 105, 0, 2 * math.pi)
        cr.set_source(rad_glow)
        cr.fill()

        # 2. Ondas Expansivas de Energía (Ripples)
        for i in range(3):
            wave_r = ((t * 22.0 + i * 28.0) % 65.0) + 38.0
            wave_fade = max(0.0, 1.0 - (wave_r - 38.0) / 65.0)
            cr.set_line_width(1.6)
            cr.set_source_rgba(r_c, g_c, b_c, wave_fade * 0.45 * alpha)
            cr.arc(cx, cy, wave_r, 0, 2 * math.pi)
            cr.stroke()

        # 3. Anillos de Reactor Giratorios
        cr.save()
        cr.translate(cx, cy)
        cr.rotate(t * speed)
        cr.set_line_width(2.4)
        cr.set_source_rgba(r_c, g_c, b_c, 0.85 * alpha)
        for i in range(3):
            ang = i * (2 * math.pi / 3)
            cr.arc(0, 0, 68, ang, ang + 1.2)
            cr.stroke()
        cr.restore()

        cr.save()
        cr.translate(cx, cy)
        cr.rotate(-t * speed * 1.4)
        cr.set_line_width(1.8)
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.75 * alpha)
        for i in range(4):
            ang = i * (2 * math.pi / 4)
            cr.arc(0, 0, 54, ang, ang + 0.8)
            cr.stroke()
        cr.restore()

        # 4. Núcleo de Plasma (Core Sphere)
        core_r = 36.0 + 3.0 * math.sin(t * 5.0)
        rad_core = cairo.RadialGradient(cx - core_r * 0.3, cy - core_r * 0.3, 2, cx, cy, core_r)
        rad_core.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.98 * alpha)
        rad_core.add_color_stop_rgba(0.35, r_c, g_c, b_c, 0.92 * alpha)
        rad_core.add_color_stop_rgba(0.80, r_c * 0.4, g_c * 0.4, b_c * 0.8, 0.80 * alpha)
        rad_core.add_color_stop_rgba(1.0, 0.05, 0.05, 0.15, 0.0)

        cr.arc(cx, cy, core_r, 0, 2 * math.pi)
        cr.set_source(rad_core)
        cr.fill()

        # 5. Insignia / Subtítulo inferior
        self.dibujar_insignia(cr, cx, h - 28, alpha)

    def dibujar_insignia(self, cr, x: float, y: float, alpha: float) -> None:
        texto = self.subtitle
        cr.select_font_face(self.font_family, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(10.5)
        extents = cr.text_extents(texto)

        badge_w = min(240, max(140, extents.width + 24))
        badge_h = 24
        bx = x - badge_w / 2.0
        by = y - badge_h / 2.0
        r = 12

        cr.new_sub_path()
        cr.arc(bx + badge_w - r, by + r, r, -math.pi / 2, 0)
        cr.arc(bx + badge_w - r, by + badge_h - r, r, 0, math.pi / 2)
        cr.arc(bx + r, by + badge_h - r, r, math.pi / 2, math.pi)
        cr.arc(bx + r, by + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

        cr.set_source_rgba(0.06, 0.04, 0.12, 0.88 * alpha)
        cr.fill_preserve()

        cr.set_line_width(1.2)
        cr.set_source_rgba(
            self.color_acento[0], self.color_acento[1], self.color_acento[2], 0.70 * alpha
        )
        cr.stroke()

        tx = x - extents.width / 2.0
        ty = y + extents.height / 2.0 - 2
        cr.move_to(tx, ty)
        cr.set_source_rgba(0.95, 0.93, 1.0, 0.95 * alpha)
        cr.show_text(texto)

    def cerrar_inmediato(self) -> None:
        if self.recorder_proc:
            try:
                self.recorder_proc.terminate()
                self.recorder_proc.kill()
            except Exception:
                pass
        self.target_alpha = 0.0
        self.state = "CLOSING"

    def on_destroy(self, widget) -> None:
        for f in (PIDFILE, STOPFILE, AUDIO_FILE):
            if f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass
        Gtk.main_quit()


def _manejar_sigusr1(signum, frame) -> None:
    STOPFILE.touch()


def lanzar_ui() -> None:
    cfg = cargar_config()
    signal.signal(signal.SIGUSR1, _manejar_sigusr1)
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")

    win = BugsitoWindow(cfg)
    win.show_all()
    Gtk.main()
