# DiagPsychro

Tracé du diagramme psychrométrique en fonction de l'altitude.

## Fonctionnalités

- Diagramme psychrométrique interactif (température sèche vs rapport de mélange)
- Réglage de la pression via l'altitude (formule ICAO)
- Courbes : saturation, humidité relative constante, isothermes, enthalpie, volume spécifique, iso teneurs en eau
- Sélection de points par clic pour analyser les processus
- Export PNG (300 DPI), SVG et PDF

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
# ou: source .venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

## Lancement

```bash
python main.py
```

## Dépendances

- Python 3.8+
- numpy
- psychrolib
- PySide6
- matplotlib
