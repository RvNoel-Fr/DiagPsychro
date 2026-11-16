import sys
import numpy as np
import psychrolib
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QDoubleSpinBox, QGroupBox,
                               QTextEdit, QPushButton, QFileDialog, QScrollArea,
                               QSizePolicy, QMessageBox)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

# Initialisation de la bibliothèque scientifique (Système SI)
psychrolib.SetUnitSystem(psychrolib.SI)

def pression_from_altitude(h_m: float) -> float:
    """Calcule la pression atmosphérique (Pa) à partir de l'altitude en mètres.
    Formule ICAO : P = P0 × (1 - h/44330)^5.255"""
    p0 = 101325  # Pa au niveau de la mer
    h = max(0, min(h_m, 44330))  # Limite physique
    return p0 * (1 - h / 44330) ** 5.255

class PsychroApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analyseur Psychrométrique Pro")
        self.resize(1400, 800)

        # Variables d'état
        self.p_atm             = 101325
        self.points_selectionnes = []
        self.orange_artists    = []
        # Mélange – sélection par clic
        self.mode_mel          = 0        # 0=inactif 1=attente A1 2=attente A2
        self.mel_a1            = None     # (t, w) Air 1
        self.mel_a2            = None     # (t, w) Air 2
        self.mel_artists       = []       # artistes du tracé mélange

        # ── Layout principal : sidebar | canvas | panneau export ──
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        root = QHBoxLayout(main_widget)
        root.setSpacing(4)

        # ── Sidebar (panneau gauche, scrollable) ──────────────────
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(220)
        sidebar = QVBoxLayout(sidebar_widget)
        sidebar.setSpacing(4)
        sidebar.setContentsMargins(4, 4, 4, 4)

        # Groupe Saisie Manuelle
        input_group = QGroupBox("Saisie Manuelle")
        input_layout = QVBoxLayout()
        input_layout.setSpacing(2)
        self.altitude_in = self.create_input(input_layout, "Altitude (m) :", 0, 5000, 0)
        self.temp_in     = self.create_input(input_layout, "T. Sèche (°C) :", -10, 50, 25)
        self.hr_in       = self.create_input(input_layout, "HR (%) :", 0, 100, 50)
        input_group.setLayout(input_layout)
        sidebar.addWidget(input_group)

        # Groupe Mélange – sélection par clic de souris
        mel_group  = QGroupBox("Mélange de 2 Airs")
        mel_layout = QVBoxLayout()
        mel_layout.setSpacing(3)

        self.mel_status = QLabel("⬜ Cliquez 'A1' puis 'A2'")
        self.mel_status.setWordWrap(True)
        font_s = QFont(); font_s.setPointSize(8)
        self.mel_status.setFont(font_s)
        mel_layout.addWidget(self.mel_status)

        btn_row = QHBoxLayout()
        self.btn_pick_a1 = QPushButton("▶ Choisir A1")
        self.btn_pick_a2 = QPushButton("▶ Choisir A2")
        self.btn_pick_a1.setCheckable(True)
        self.btn_pick_a2.setCheckable(True)
        self.btn_pick_a1.clicked.connect(self._activer_sel_a1)
        self.btn_pick_a2.clicked.connect(self._activer_sel_a2)
        btn_row.addWidget(self.btn_pick_a1)
        btn_row.addWidget(self.btn_pick_a2)
        mel_layout.addLayout(btn_row)

        self.q1_mel_in = self.create_input(mel_layout, "Débit A1 (kg/s) :", 0.01, 100, 1.0)
        self.q2_mel_in = self.create_input(mel_layout, "Débit A2 (kg/s) :", 0.01, 100, 1.0)

        self.btn_calc_mel = QPushButton("Calculer Mélange")
        self.btn_calc_mel.setEnabled(False)
        self.btn_calc_mel.clicked.connect(self.calculer_melange)
        mel_layout.addWidget(self.btn_calc_mel)
        mel_group.setLayout(mel_layout)
        sidebar.addWidget(mel_group)

        # Groupe Batterie Froide
        bf_group = QGroupBox("Batterie Froide")
        bf_layout = QVBoxLayout()
        bf_layout.setSpacing(2)
        self.tbf_in    = self.create_input(bf_layout, "T. BF (°C) :", -20, 50, 5)
        self.eff_bf_in = self.create_input(bf_layout, "Efficacité (%) :", 0, 100, 80)
        btn_bf = QPushButton("Calculer BF")
        btn_bf.clicked.connect(self.calculer_batterie_froide)
        bf_layout.addWidget(btn_bf)
        bf_group.setLayout(bf_layout)
        sidebar.addWidget(bf_group)

        # Zone Log
        sidebar.addWidget(QLabel("Analyse du Processus :"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Cliquez sur le graphique pour définir un processus...")
        sidebar.addWidget(self.log_box)

        btn_effacer = QPushButton("Effacer les points")
        btn_effacer.clicked.connect(self.effacer_points)
        sidebar.addWidget(btn_effacer)
        sidebar.addStretch()

        root.addWidget(sidebar_widget, 0)

        # ── Canvas (zone graphique centrale) ──────────────────────
        self.figure = Figure(figsize=(12, 8), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        root.addWidget(self.canvas, 1)

        # ── Panneau Export & Outils (droite) ──────────────────────
        export_widget = QWidget()
        export_widget.setFixedWidth(95)
        export_layout = QVBoxLayout(export_widget)
        export_layout.setSpacing(6)
        export_layout.setContentsMargins(4, 4, 4, 4)

        export_layout.addWidget(QLabel("Export :"))
        for fmt in ("PNG", "SVG", "PDF"):
            b = QPushButton(fmt)
            b.clicked.connect(lambda checked, f=fmt.lower(): self.exporter_graphique(f))
            export_layout.addWidget(b)

        export_layout.addSpacing(10)
        export_layout.addWidget(QLabel("Outils :"))

        self.btn_copier_log = QPushButton("📋 Copier\nAnalyse")
        self.btn_copier_log.clicked.connect(self.copier_analyse)
        export_layout.addWidget(self.btn_copier_log)

        btn_aide = QPushButton("❓ Aide")
        btn_aide.clicked.connect(self.afficher_aide)
        export_layout.addWidget(btn_aide)

        export_layout.addStretch()
        root.addWidget(export_widget, 0)

        # ── Initialisation ─────────────────────────────────────────
        self.setup_chart()
        self.altitude_in.valueChanged.connect(self.on_altitude_change)
        self.temp_in.valueChanged.connect(self.update_from_inputs)
        self.hr_in.valueChanged.connect(self.update_from_inputs)
        self.canvas.mpl_connect('button_press_event', self.on_click)
        self.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)

    # ── Helpers sélection mélange ──────────────────────────────────
    def _activer_sel_a1(self):
        self.mode_mel = 1
        self.btn_pick_a1.setChecked(True)
        self.btn_pick_a2.setChecked(False)
        self.mel_status.setText("🔵 Cliquez sur le graphique → Air 1")

    def _activer_sel_a2(self):
        self.mode_mel = 2
        self.btn_pick_a2.setChecked(True)
        self.btn_pick_a1.setChecked(False)
        self.mel_status.setText("🔴 Cliquez sur le graphique → Air 2")

    def _reset_sel_mel(self):
        self.mode_mel = 0
        self.btn_pick_a1.setChecked(False)
        self.btn_pick_a2.setChecked(False)

    def create_input(self, layout, label, mini, maxi, default):
        layout.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(mini, maxi)
        spin.setValue(default)
        layout.addWidget(spin)
        return spin

    def on_altitude_change(self):
        """Recalcule la pression, efface les points, et met à jour tout le diagramme."""
        self.p_atm = pression_from_altitude(self.altitude_in.value())
        self.points_selectionnes = []
        for artist in self.orange_artists:
            artist.remove()
        self.orange_artists.clear()
        # Supprimer la référence au marker avant ax.clear() pour éviter
        # une tentative de remove() sur un artiste déjà effacé
        if hasattr(self, 'current_marker'):
            del self.current_marker
        self.setup_chart()
        self.update_from_inputs()

    def setup_chart(self):
        """Trace le fond du diagramme (Saturation, Isothermes, Enthalpies)."""
        self.ax.clear()
        temps = np.linspace(-10, 50, 100)
        
        # 1. Courbe de Saturation (100% HR)
        w_sat = [psychrolib.GetSatHumRatio(t, self.p_atm) for t in temps]
        self.ax.plot(temps, w_sat, color='dimgray', linewidth=1.5, label="Saturation")

        # 2. Lignes iso teneurs en eau (w constant), pas 0.001, à droite de la courbe de saturation
        for w_val in np.arange(0.001, 0.030, 0.001):
            t_sat = np.interp(w_val, w_sat, temps)  # T où la ligne rencontre la saturation
            if -10 <= t_sat < 50:
                self.ax.plot([t_sat, 50], [w_val, w_val], color='lightgray', linestyle='-', linewidth=0.8)

        # 3. Courbes à humidité relative constante (10%, 20%, ..., 90%)
        for hr_pct in range(10, 100, 10):
            hr = hr_pct / 100
            w_hr = []
            t_hr = []
            for t in temps:
                try:
                    w = psychrolib.GetHumRatioFromRelHum(t, hr, self.p_atm)
                    if 0 <= w <= 0.030:  # Dans les limites du graphique
                        w_hr.append(w)
                        t_hr.append(t)
                except ValueError:
                    pass
            if t_hr:
                self.ax.plot(t_hr, w_hr, 'b--', alpha=0.4, linewidth=1)
                # Labels au milieu de chaque courbe pour faciliter la lecture
                mid = len(t_hr) // 2
                self.ax.text(t_hr[mid], w_hr[mid], f" {hr_pct}%", color='blue', fontsize=7, alpha=0.7,
                             horizontalalignment='left', verticalalignment='center')

        # 4. Isothermes sèches (verticales, tous les degrés)
        for t in range(-10, 51, 1):
            w_max = psychrolib.GetSatHumRatio(t, self.p_atm)
            self.ax.plot([t, t], [0, w_max], color='gray', linestyle=':', alpha=0.25)

        # 5. Lignes d'Enthalpie constante (Diagonales)
        # Formule : w = (h - Cpa*T) / (Hfg + Cpw*T)
        for h in range(-10, 130, 5):
            h_w = [(h - 1.006 * t) / (2501 + 1.86 * t) for t in temps]
            # On filtre pour rester sous la saturation
            valid_t = [t for i, t in enumerate(temps) if 0 <= h_w[i] <= w_sat[i]]
            valid_w = [w for i, w in enumerate(h_w) if 0 <= h_w[i] <= w_sat[i]]
            if valid_w:
                self.ax.plot(valid_t, valid_w, 'g--', alpha=0.2)
                # Placer la légende de l'enthalpie à la fin de la courbe (vers la droite / le bas)
                t_end = valid_t[-1]
                w_end = valid_w[-1]
                # Aligner selon la position de sortie
                ha = 'left' if t_end < 49 else 'right'
                self.ax.text(t_end, w_end, f" {h}", color='green', fontsize=8,
                             verticalalignment='bottom', horizontalalignment=ha)

        # 6. Lignes de volume spécifique constant (m³/kg)
        w_vals = np.linspace(0.001, 0.028, 80)
        for v_m3 in np.arange(0.80, 0.97, 0.02):
            t_vol = []
            w_vol = []
            for w in w_vals:
                try:
                    t = psychrolib.GetTDryBulbFromMoistAirVolumeAndHumRatio(v_m3, w, self.p_atm)
                    w_sat_t = psychrolib.GetSatHumRatio(t, self.p_atm)
                    if -10 <= t <= 50 and 0 <= w <= 0.030 and w <= w_sat_t:
                        t_vol.append(t)
                        w_vol.append(w)
                except ValueError:
                    pass
            if t_vol:
                # Trier par T pour un tracé propre
                pts = sorted(zip(t_vol, w_vol))
                t_vol, w_vol = [p[0] for p in pts], [p[1] for p in pts]
                self.ax.plot(t_vol, w_vol, 'm:', alpha=0.35, linewidth=1)
                self.ax.text(t_vol[0], w_vol[0], f" {v_m3:.2f}", color='magenta', fontsize=7, alpha=0.7)

        self.ax.set_xlim(-10, 50)
        self.ax.set_ylim(0, 0.030)
        self.ax.set_title(f"Diagramme Psychrométrique - {int(self.p_atm)} Pa")
        self.ax.set_xlabel("Température Sèche (°C)")
        # Axe des ordonnées (teneur en eau) à droite
        self.ax.yaxis.tick_right()
        self.ax.yaxis.set_label_position("right")
        self.ax.set_ylabel("Rapport de mélange (kg/kg air sec)")

        # Légendes dans l'espace vide à gauche (avec type de tracé)
        legend_handles = [
            Line2D([0], [0], color='dimgray', linestyle='-', linewidth=1.5, label='Saturation (100 % HR)'),
            Line2D([0], [0], color='lightgray', linestyle='-', linewidth=1, label='Iso teneurs en eau'),
            Line2D([0], [0], color='blue', linestyle='--', linewidth=1, label='Humidité relative constante'),
            Line2D([0], [0], color='gray', linestyle=':', linewidth=1, label='Isothermes'),
            Line2D([0], [0], color='green', linestyle='--', linewidth=1, alpha=0.8, label='Enthalpie constante'),
            Line2D([0], [0], color='magenta', linestyle=':', linewidth=1, alpha=0.8, label='Volume spécifique'),
        ]
        self.ax.legend(handles=legend_handles, loc='center left', fontsize=8,
                       framealpha=0.95, edgecolor='gray')

        # Ajout du conteneur de texte pour le survol de souris
        self.hover_text = self.ax.text(0.02, 0.98, "", transform=self.ax.transAxes, 
                                       verticalalignment='top', fontsize=9,
                                       bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor='gray'))
        self.hover_text.set_visible(False)

        self.canvas.draw()

    def update_from_inputs(self):
        t = self.temp_in.value()
        hr = self.hr_in.value()
        try:
            w = psychrolib.GetHumRatioFromRelHum(t, hr/100, self.p_atm)
            h = psychrolib.GetMoistAirEnthalpy(t, w)
            self.log_box.setText(f"POINT ACTUEL :\nTemp: {t}°C\nHR: {hr}%\nEnthalpie: {h/1000:.2f} kJ/kg")
            self.plot_point(t, w)
        except (ValueError, OverflowError):
            self.log_box.setText("ERREUR : Point hors limites physiques !")

    def plot_point(self, t, w):
        if hasattr(self, 'current_marker'):
            try:
                self.current_marker.remove()
            except Exception:
                pass  # Le marker a déjà été effacé par ax.clear()
        self.current_marker = self.ax.scatter(t, w, color='blue', s=80, edgecolors='white', zorder=5)
        self.canvas.draw()

    def on_mouse_move(self, event):
        if hasattr(self, 'hover_text'):
            if event.inaxes:
                t, w = event.xdata, event.ydata
                # Vérification : Seulement sous la courbe de saturation et limites physiquement vraisemblables
                if -15 <= t <= 55 and w >= 0:
                    sat_w = psychrolib.GetSatHumRatio(t, self.p_atm)
                    if w <= sat_w:
                        h = psychrolib.GetMoistAirEnthalpy(t, w)
                        p_hpa = self.p_atm / 100.0
                        info = f"Patm = {p_hpa:.1f} hPa\nEnthalpie = {h/1000:.2f} kJ/kg\nT = {t:.1f}°C\nW = {w*1000:.2f} g/kg"
                        self.hover_text.set_text(info)
                        self.hover_text.set_visible(True)
                        self.canvas.draw_idle()
                        return
            
            # En dehors de la zone valide ou hors du plot
            if self.hover_text.get_visible():
                self.hover_text.set_visible(False)
                self.canvas.draw_idle()

    def on_click(self, event):
        if not event.inaxes:
            return
        t, w = event.xdata, event.ydata
        if w > psychrolib.GetSatHumRatio(t, self.p_atm):
            return  # hors zone valide

        # ── Mode sélection mélange ─────────────────────────────────
        if self.mode_mel == 1:
            self.mel_a1 = (t, w)
            # Effacer ancien marqueur A1 s'il existe
            for a in [a for a in self.mel_artists if getattr(a, '_mel_role', '') == 'a1']:
                try: a.remove()
                except: pass
            self.mel_artists = [a for a in self.mel_artists if getattr(a, '_mel_role', '') != 'a1']
            sc = self.ax.scatter(t, w, color='royalblue', s=70, edgecolors='white', zorder=6)
            sc._mel_role = 'a1'
            lbl = self.ax.text(t, w + 0.0006, 'A1', color='royalblue',
                               fontsize=9, fontweight='bold', ha='center')
            lbl._mel_role = 'a1'
            self.mel_artists.extend([sc, lbl])
            self.canvas.draw()
            self._reset_sel_mel()
            self.mel_status.setText(f"🔵 A1 : T={t:.1f}°C  w={w*1000:.2f} g/kg")
            self._check_mel_ready()
            return

        if self.mode_mel == 2:
            self.mel_a2 = (t, w)
            for a in [a for a in self.mel_artists if getattr(a, '_mel_role', '') == 'a2']:
                try: a.remove()
                except: pass
            self.mel_artists = [a for a in self.mel_artists if getattr(a, '_mel_role', '') != 'a2']
            sc = self.ax.scatter(t, w, color='tomato', s=70, edgecolors='white', zorder=6)
            sc._mel_role = 'a2'
            lbl = self.ax.text(t, w + 0.0006, 'A2', color='tomato',
                               fontsize=9, fontweight='bold', ha='center')
            lbl._mel_role = 'a2'
            self.mel_artists.extend([sc, lbl])
            self.canvas.draw()
            self._reset_sel_mel()
            self.mel_status.setText(f"🔴 A2 : T={t:.1f}°C  w={w*1000:.2f} g/kg")
            self._check_mel_ready()
            return

        # ── Mode normal : sélection processus A→B ─────────────────
        self.points_selectionnes.append((t, w))
        sc = self.ax.scatter(t, w, color='orange', s=40)
        self.orange_artists.append(sc)
        if len(self.points_selectionnes) == 2:
            self.calculer_processus()
            self.points_selectionnes = []
        self.canvas.draw()

    def _check_mel_ready(self):
        """Active le bouton Calculer Mélange si A1 et A2 sont définis."""
        self.btn_calc_mel.setEnabled(self.mel_a1 is not None and self.mel_a2 is not None)
        if self.mel_a1 and self.mel_a2:
            self.mel_status.setText(
                f"🔵 A1: {self.mel_a1[0]:.1f}°C  🔴 A2: {self.mel_a2[0]:.1f}°C\n"
                f"→ Prêt à calculer")

    def calculer_processus(self):
        p1, p2 = self.points_selectionnes
        t1, w1 = p1
        t2, w2 = p2

        h1 = psychrolib.GetMoistAirEnthalpy(t1, w1)
        h2 = psychrolib.GetMoistAirEnthalpy(t2, w2)
        delta_h = (h2 - h1) / 1000          # kJ/kg d'air sec
        delta_w = (w2 - w1) * 1000           # g/kg d'air sec (+ humidification, - déshumidification)

        # Humidité relative de chaque point
        hr1 = psychrolib.GetRelHumFromHumRatio(t1, w1, self.p_atm) * 100
        hr2 = psychrolib.GetRelHumFromHumRatio(t2, w2, self.p_atm) * 100

        # Nature du processus
        if abs(delta_w) < 0.01:
            nature_w = "Processus sans échange de vapeur (chauffage/refroidissement sensible)"
        elif delta_w > 0:
            nature_w = "Humidification"
        else:
            nature_w = "Déshumidification"

        # Tracé de la ligne de processus
        line, = self.ax.plot([t1, t2], [w1, w2], 'orange', lw=2, linestyle='-')
        # Ajout des lettres A et B au-dessus des points
        off_y = 0.0005
        text_a = self.ax.text(t1, w1 + off_y, 'A', color='black', fontsize=10, fontweight='bold', ha='center')
        text_b = self.ax.text(t2, w2 + off_y, 'B', color='black', fontsize=10, fontweight='bold', ha='center')
        self.orange_artists.extend([line, text_a, text_b])

        msg = (f"NOUVEAU PROCESSUS :\n"
               f"Point A : T={t1:.1f}°C  w={w1*1000:.2f} g/kg  HR={hr1:.1f}%\n"
               f"Point B : T={t2:.1f}°C  w={w2*1000:.2f} g/kg  HR={hr2:.1f}%\n"
               f"{'─'*28}\n"
               f"Δh = {delta_h:+.2f} kJ/kg d'air sec\n"
               f"Δw = {delta_w:+.2f} g/kg d'air sec\n"
               f"Puissance pour 1 kg/s : {delta_h:.2f} kW\n"
               f"→ {nature_w}")
        self.log_box.append("\n" + "─"*28 + "\n" + msg)

    def calculer_melange(self):
        """Calcule et trace le mélange adiabatique — points sélectionnés par clic."""
        if self.mel_a1 is None or self.mel_a2 is None:
            self.log_box.append("\nMélange : sélectionnez d'abord A1 et A2 sur le graphique.")
            return

        t1, w1 = self.mel_a1
        t2, w2 = self.mel_a2
        q1 = self.q1_mel_in.value()
        q2 = self.q2_mel_in.value()

        try:
            h1 = psychrolib.GetMoistAirEnthalpy(t1, w1)
            h2 = psychrolib.GetMoistAirEnthalpy(t2, w2)
            hr1 = psychrolib.GetRelHumFromHumRatio(t1, w1, self.p_atm) * 100
            hr2 = psychrolib.GetRelHumFromHumRatio(t2, w2, self.p_atm) * 100

            q_tot = q1 + q2
            # Loi de mélange adiabatique (conservation de h et w)
            w_m = (q1 * w1 + q2 * w2) / q_tot
            h_m = (q1 * h1 + q2 * h2) / q_tot

            # Température du mélange : h = Cpa*T + w*(Hfg + Cpw*T)
            Cpa, Cpw, Hfg = 1006.0, 1860.0, 2501000.0
            t_m = (h_m - w_m * Hfg) / (Cpa + w_m * Cpw)
            hr_m  = psychrolib.GetRelHumFromHumRatio(t_m, w_m, self.p_atm) * 100
            ratio = q1 / q_tot * 100

            # ── Effacer anciens artistes mélange ──
            for a in self.mel_artists:
                try: a.remove()
                except: pass
            self.mel_artists.clear()

            # ── Tracé ──
            sc1 = self.ax.scatter(t1, w1, color='royalblue', s=70, edgecolors='white', zorder=6)
            sc2 = self.ax.scatter(t2, w2, color='tomato',    s=70, edgecolors='white', zorder=6)
            scm = self.ax.scatter(t_m, w_m, color='purple',  s=90, edgecolors='white',
                                  marker='D', zorder=7)
            off = 0.0006
            lbl1 = self.ax.text(t1,  w1  + off, 'A1', color='royalblue',
                                fontsize=9, fontweight='bold', ha='center')
            lbl2 = self.ax.text(t2,  w2  + off, 'A2', color='tomato',
                                fontsize=9, fontweight='bold', ha='center')
            lblm = self.ax.text(t_m, w_m + off, 'M',  color='purple',
                                fontsize=9, fontweight='bold', ha='center')
            line_mel, = self.ax.plot([t1, t_m, t2], [w1, w_m, w2],
                                     color='purple', lw=1.5, linestyle='--', zorder=5)
            self.mel_artists.extend([sc1, sc2, scm, lbl1, lbl2, lblm, line_mel])
            self.canvas.draw()

            msg = (f"MÉLANGE ADIABATIQUE :\n"
                   f"A1 : T={t1:.1f}°C  w={w1*1000:.2f} g/kg  HR={hr1:.0f}%  q={q1:.2f} kg/s\n"
                   f"A2 : T={t2:.1f}°C  w={w2*1000:.2f} g/kg  HR={hr2:.0f}%  q={q2:.2f} kg/s\n"
                   f"{'─'*28}\n"
                   f"Ratio : {ratio:.1f}% A1 / {100-ratio:.1f}% A2\n"
                   f"Point M (mélange) :\n"
                   f"  T  = {t_m:.2f} °C\n"
                   f"  w  = {w_m*1000:.3f} g/kg\n"
                   f"  HR = {hr_m:.1f} %\n"
                   f"  h  = {h_m/1000:.2f} kJ/kg\n"
                   f"  Débit total = {q_tot:.2f} kg/s")
            self.log_box.append("\n" + "─"*28 + "\n" + msg)

        except Exception as e:
            self.log_box.append(f"\nErreur Mélange : {e}")

    def calculer_batterie_froide(self):
        t_A = self.temp_in.value()
        hr_A = self.hr_in.value()
        t_bf = self.tbf_in.value()
        eff = self.eff_bf_in.value() / 100.0
        
        try:
            w_A = psychrolib.GetHumRatioFromRelHum(t_A, hr_A / 100.0, self.p_atm)
            h_A = psychrolib.GetMoistAirEnthalpy(t_A, w_A)
            
            # Point batterie à l'état de saturation
            w_bf = psychrolib.GetSatHumRatio(t_bf, self.p_atm)
            
            # Point B : Sortie de batterie (bypass factor)
            t_B = t_A * (1 - eff) + t_bf * eff
            w_B = w_A * (1 - eff) + w_bf * eff
            
            # Limiter W_B à la saturation s'il dépasse physiquement (sécurité)
            w_sat_B = psychrolib.GetSatHumRatio(t_B, self.p_atm)
            if w_B > w_sat_B:
                w_B = w_sat_B
                
            h_B = psychrolib.GetMoistAirEnthalpy(t_B, w_B)
            
            delta_h = (h_B - h_A) / 1000.0 # kJ/kg
            delta_w = (w_B - w_A) * 1000.0 # g/kg
            
            # Tracé
            line, = self.ax.plot([t_A, t_B], [w_A, w_B], 'cyan', lw=2, linestyle='-')
            sc = self.ax.scatter(t_B, w_B, color='cyan', s=60, edgecolors='black', zorder=6)
            self.orange_artists.extend([line, sc])
            
            msg = (f"BATTERIE FROIDE :\n"
                   f"Entrée : T={t_A:.1f}°C, HR={hr_A:.1f}%\n"
                   f"Sortie : T={t_B:.1f}°C\n"
                   f"Δh = {delta_h:.2f} kJ/kg d'air sec\n"
                   f"ΔW = {delta_w:.2f} g/kg d'air sec")
            self.log_box.append("\n" + "-"*20 + "\n" + msg)
            self.canvas.draw()
            
        except Exception as e:
            self.log_box.append(f"\nErreur Batterie Froide : paramètres hors limites.")

    def effacer_points(self):
        """Réinitialise les points, efface les processus tracés et la zone de log."""
        self.points_selectionnes = []
        for artist in self.orange_artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self.orange_artists.clear()
        # Effacer aussi les artistes du mélange
        for artist in self.mel_artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self.mel_artists.clear()
        self.mel_a1 = None
        self.mel_a2 = None
        self.btn_calc_mel.setEnabled(False)
        self.mel_status.setText("⬜ Cliquez 'A1' puis 'A2'")
        self._reset_sel_mel()
        self.log_box.clear()
        self.update_from_inputs()
        self.canvas.draw()

    def exporter_graphique(self, format_fichier: str):
        """Exporte le graphique dans le format spécifié (png, svg ou pdf)."""
        filtres = {
            "png": "Images PNG (*.png)",
            "svg": "Images SVG (*.svg)",
            "pdf": "Documents PDF (*.pdf)",
        }
        chemin, _ = QFileDialog.getSaveFileName(
            self, f"Exporter en {format_fichier.upper()}",
            f"diagramme_psychrometrique.{format_fichier}",
            filtres[format_fichier]
        )
        if chemin:
            opts = {'format': format_fichier, 'bbox_inches': 'tight'}
            if format_fichier == 'png':
                opts['dpi'] = 300
            self.figure.savefig(chemin, **opts)

    def copier_analyse(self):
        """Copie le contenu de la zone 'Analyse du Processus' dans le presse-papier."""
        texte = self.log_box.toPlainText().strip()
        if not texte:
            texte_a_copier = "Aucune analyse disponible pour le moment."
        else:
            texte_a_copier = texte
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(texte_a_copier)

        # Petit feedback visuel sur le bouton
        texte_origine = self.btn_copier_log.text()
        self.btn_copier_log.setText("✅ Copié !")
        QTimer.singleShot(1500, lambda: self.btn_copier_log.setText(texte_origine))

    def afficher_aide(self):
        """Affiche une boîte de dialogue explicative sur l'utilisation du diagramme."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Aide - Analyseur Psychrométrique Pro")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            "<h3>💡 Guide d'utilisation</h3>"
            "<p><b>1. Analyse d'une évolution (Processus A → B) :</b><br>"
            "Vous pouvez évaluer n'importe quelle transformation d'air en <b>cliquant successivement sur 2 points</b> du diagramme psychrométrique :<br>"
            "• <b>1<sup>er</sup> clic :</b> Définit l'état initial (Point A)<br>"
            "• <b>2<sup>nd</sup> clic :</b> Définit l'état final (Point B)<br>"
            "L'application trace le processus en orange et calcule automatiquement :<br>"
            "&nbsp;&nbsp;- La variation d'enthalpie <b>Δh</b> (kJ/kg d'air sec)<br>"
            "&nbsp;&nbsp;- La variation de teneur en vapeur d'eau <b>Δw</b> (g/kg d'air sec)<br>"
            "&nbsp;&nbsp;- La puissance thermique équivalente pour 1 kg/s d'air sec<br>"
            "&nbsp;&nbsp;- La nature du processus (chauffage sensible, humidification, déshumidification...)</p>"
            "<p><b>2. Mélange de 2 flux d'air :</b><br>"
            "• Cliquez sur <i>'Choisir A1'</i> puis cliquez sur le diagramme.<br>"
            "• Cliquez sur <i>'Choisir A2'</i> puis cliquez sur le diagramme.<br>"
            "• Ajustez les débits massiques (kg/s) puis cliquez sur <i>'Calculer Mélange'</i>.<br>"
            "Le point résultant <b>M</b> est positionné et analysé.</p>"
            "<p><b>3. Outils :</b><br>"
            "• <b>Effacer les points :</b> Réinitialise les tracés.<br>"
            "• <b>Copier Analyse :</b> Copie l'intégralité du compte-rendu dans le presse-papier.<br>"
            "• <b>Export :</b> Sauvegarde le diagramme en PNG (haute résolution 300 DPI), SVG ou PDF.</p>"
        )
        msg.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PsychroApp()
    window.show()
    sys.exit(app.exec())
