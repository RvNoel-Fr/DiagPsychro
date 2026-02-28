import sys
import numpy as np
import psychrolib
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QDoubleSpinBox, QGroupBox, QTextEdit, QPushButton,
                             QFileDialog)
from PySide6.QtCore import Qt
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
        self.resize(1200, 800)

        # Variables d'état
        self.p_atm = 101325  # Pression au niveau de la mer (Pa)
        self.points_selectionnes = []
        self.orange_artists = []  # Références aux tracés orange pour pouvoir les effacer

        # --- Interface ---
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Panneau latéral
        sidebar = QVBoxLayout()
        
        # Groupe Inputs
        input_group = QGroupBox("Saisie Manuelle")
        input_layout = QVBoxLayout()
        
        self.altitude_in = self.create_input(input_layout, "Altitude (m) :", 0, 5000, 0)
        self.temp_in = self.create_input(input_layout, "Temp. Sèche (°C) :", -10, 50, 25)
        self.hr_in = self.create_input(input_layout, "Humidité Rel. (%) :", 0, 100, 50)
        input_group.setLayout(input_layout)
        sidebar.addWidget(input_group)

        # Zone de Log / Résultats
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Cliquez sur le graphique pour définir un processus...")
        sidebar.addWidget(QLabel("Analyse du Processus :"))
        sidebar.addWidget(self.log_box)

        btn_effacer = QPushButton("Effacer les points")
        btn_effacer.clicked.connect(self.effacer_points)
        sidebar.addWidget(btn_effacer)

        # Boutons d'export
        sidebar.addWidget(QLabel("Exporter le graphique :"))
        btn_png = QPushButton("PNG")
        btn_png.clicked.connect(lambda: self.exporter_graphique("png"))
        sidebar.addWidget(btn_png)
        btn_svg = QPushButton("SVG")
        btn_svg.clicked.connect(lambda: self.exporter_graphique("svg"))
        sidebar.addWidget(btn_svg)
        btn_pdf = QPushButton("PDF")
        btn_pdf.clicked.connect(lambda: self.exporter_graphique("pdf"))
        sidebar.addWidget(btn_pdf)
        
        layout.addLayout(sidebar, 1)

        # Zone Graphique
        self.figure = Figure(figsize=(10, 8), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)
        layout.addWidget(self.canvas, 4)

        # Initialisation du tracé
        self.setup_chart()
        
        # Événements
        self.altitude_in.valueChanged.connect(self.on_altitude_change)
        self.temp_in.valueChanged.connect(self.update_from_inputs)
        self.hr_in.valueChanged.connect(self.update_from_inputs)
        self.canvas.mpl_connect('button_press_event', self.on_click)

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
        for h in range(0, 101, 20):
            h_w = [(h - 1.006 * t) / (2501 + 1.86 * t) for t in temps]
            # On filtre pour rester sous la saturation
            valid_t = [t for i, t in enumerate(temps) if 0 <= h_w[i] <= w_sat[i]]
            valid_w = [w for i, w in enumerate(h_w) if 0 <= h_w[i] <= w_sat[i]]
            if valid_w:
                self.ax.plot(valid_t, valid_w, 'g--', alpha=0.2)
                self.ax.text(valid_t[0], valid_w[0], f"{h}", color='green', fontsize=8)

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

        self.canvas.draw()

    def update_from_inputs(self):
        t = self.temp_in.value()
        hr = self.hr_in.value()
        try:
            w = psychrolib.GetHumRatioFromRelHum(t, hr/100, self.p_atm)
            h = psychrolib.GetMoistAirEnthalpy(t, w)
            self.log_box.setText(f"POINT ACTUEL :\nTemp: {t}°C\nHR: {hr}%\nEnthalpie: {h/1000:.2f} kJ/kg")
            self.plot_point(t, w)
        except:
            self.log_box.setText("ERREUR : Point hors limites physiques !")

    def plot_point(self, t, w):
        if hasattr(self, 'current_marker'):
            self.current_marker.remove()
        self.current_marker = self.ax.scatter(t, w, color='blue', s=80, edgecolors='white', zorder=5)
        self.canvas.draw()

    def on_click(self, event):
        if event.inaxes:
            t, w = event.xdata, event.ydata
            # Vérifier si le clic est sous la courbe de saturation
            if w <= psychrolib.GetSatHumRatio(t, self.p_atm):
                self.points_selectionnes.append((t, w))
                sc = self.ax.scatter(t, w, color='orange', s=40)
                self.orange_artists.append(sc)
                
                if len(self.points_selectionnes) == 2:
                    self.calculer_processus()
                    self.points_selectionnes = []
                self.canvas.draw()

    def calculer_processus(self):
        p1, p2 = self.points_selectionnes
        h1 = psychrolib.GetMoistAirEnthalpy(p1[0], p1[1])
        h2 = psychrolib.GetMoistAirEnthalpy(p2[0], p2[1])
        delta_h = (h2 - h1) / 1000 # kJ/kg
        
        # Tracé de la ligne de processus
        line, = self.ax.plot([p1[0], p2[0]], [p1[1], p2[1]], 'orange', lw=2, linestyle='-')
        self.orange_artists.append(line)
        
        msg = (f"NOUVEAU PROCESSUS :\n"
               f"Point A -> Point B\n"
               f"Δh = {delta_h:.2f} kJ/kg d'air sec\n"
               f"Puissance pour 1 kg/s : {delta_h:.2f} kW")
        self.log_box.append("\n" + "-"*20 + "\n" + msg)

    def effacer_points(self):
        """Réinitialise les points, efface les processus tracés et la zone de log."""
        self.points_selectionnes = []
        for artist in self.orange_artists:
            try:
                artist.remove()
            except (ValueError, AttributeError):
                pass
        self.orange_artists.clear()
        self.log_box.clear()
        self.update_from_inputs()  # Restaure l'affichage du point manuel actuel
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PsychroApp()
    window.show()
    sys.exit(app.exec())
