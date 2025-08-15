# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtCore import QTimer
from graphics_ui import Ui_MainWindow
import sys
import minimalmodbus
import serial
from serial.tools import list_ports
import csv
from datetime import datetime
import configparser

#––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
# Configuración Modbus RTU para PowerFlex 525
#––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
MODBUS_PORT     = 'COM5'
MODBUS_BAUDRATE = 9600   # PowerFlex 525 default
MODBUS_SLAVE_ID = 100
MAX_FREQUENCY   = 70      # Límite máximo de frecuencia en Hz

# Registros Modbus (offsets 0-based para minimalmodbus)
REG_CONTROL = 8192   # Control Word (N41:0)
REG_SPEED   = 8193   # Speed Reference (N41:1)
REG_STATUS  = 8448   # Status Word (N41:3)

# Comandos Control Word bits para PowerFlex 525
CMD_STOP        = 1
CMD_RUN_FORWARD = 22
CMD_RUN_REVERSE = 34

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        #–– Indicador de conexión
        self.ui.label_connection.setText("Desconectado")
        self.ui.label_connection.setStyleSheet("background-color: #AA0000; color: white;")

        #–– Logs y configuraciones
        self.test_log = []
        self.automated_configs = {}

        #–– Intentar conectar RS-485 Modbus RTU
        try:
            self.instrument = minimalmodbus.Instrument(MODBUS_PORT, MODBUS_SLAVE_ID)
            self.instrument.serial.baudrate = MODBUS_BAUDRATE
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity   = serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout  = 1
            self.instrument.mode = minimalmodbus.MODE_RTU
            self._update_connection_indicator(True)
        except Exception as e:
            print(f"Error abriendo puerto {MODBUS_PORT}: {e}")
            ports = [p.device for p in list_ports.comports()]
            print("Puertos disponibles:", ports)
            self.instrument = None
            self._update_connection_indicator(False)

        #–– Conectar botones de página
        self.ui.pushButton.clicked.connect(self.show_manual_mode)
        self.ui.pushButton_2.clicked.connect(self.show_automated_mode)
        self.ui.stackedWidget.setCurrentIndex(0)

        #–– MANUAL MODE
        self.ui.pushButton_4.clicked.connect(self.on_manual_on)
        self.ui.pushButton_5.clicked.connect(self.on_manual_off)
        self.ui.dial.valueChanged.connect(self.on_dial_changed)

        #–– AUTOMATED MODE
        self.ui.pushButton_15.clicked.connect(self.load_configuration)
        self.ui.pushButton_16.clicked.connect(self.delete_configuration)
        self.ui.pushButton_17.clicked.connect(self.apply_configuration)

        # === Timer para leer frecuencia real continuamente ===
        self.freq_timer = QTimer(self)
        self.freq_timer.timeout.connect(self.update_real_frequency)
        self.freq_timer.start(500)  # cada 500 ms

    #––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # Indicador de conexión
    def _update_connection_indicator(self, ok: bool):
        if ok:
            self.ui.label_connection.setText("Conectado")
            self.ui.label_connection.setStyleSheet("background-color: #00AA00; color: white;")
        else:
            self.ui.label_connection.setText("Desconectado")
            self.ui.label_connection.setStyleSheet("background-color: #AA0000; color: white;")

    #––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # Navegación de páginas
    def show_manual_mode(self):    self.ui.stackedWidget.setCurrentIndex(0)
    def show_automated_mode(self): self.ui.stackedWidget.setCurrentIndex(1)

    #––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # Modbus: comandos básicos con indicador para PowerFlex 525
    def command_start(self, direction='FWD'):
        if not self.instrument: return
        try:
            if direction == 'FWD':
                self.instrument.write_register(REG_CONTROL, CMD_RUN_FORWARD, 0, functioncode=16)
            elif direction == 'REV':
                self.instrument.write_register(REG_CONTROL, CMD_RUN_REVERSE, 0, functioncode=16)
            else:
                self.instrument.write_register(REG_CONTROL, CMD_STOP, 0, functioncode=16)
            self._update_connection_indicator(True)
        except:
            self._update_connection_indicator(False)

    def command_stop(self):
        if not self.instrument: return
        try:
            self.instrument.write_register(REG_CONTROL, CMD_STOP, 0, functioncode=16)
            self._update_connection_indicator(True)
        except:
            self._update_connection_indicator(False)

    def set_frequency(self, hz):
        if not self.instrument: return
        try:
            hz_scaled = int(hz * 100)
            self.instrument.write_register(REG_SPEED, hz_scaled, 0, functioncode=16)
            self._update_connection_indicator(True)
        except:
            self._update_connection_indicator(False)

    def read_status(self):
        if not self.instrument:
            self._update_connection_indicator(False)
            return {'raw': None, 'running': False, 'direction': 'UNKNOWN', 'fault': False}
        try:
            raw = self.instrument.read_register(REG_STATUS, 0, functioncode=3)
            self._update_connection_indicator(True)
        except:
            self._update_connection_indicator(False)
            return {'raw': None, 'running': False, 'direction': 'UNKNOWN', 'fault': False}

        running = raw & 0x0002
        forward = raw & 0x0008
        reverse = bool(raw & (1 << 2))   # Bit 2 = REVERSE
        fault   = raw & 0x0080

        direction = 'FWD' if forward else 'REV'
        return {'raw': raw, 'running': running, 'direction': direction, 'fault': fault}

    # Lectura de frecuencia y actualización de estado
    def update_real_frequency(self):
        if not self.instrument:
            return
        try:
            freq = self.instrument.read_register(8451, 2, functioncode=3)  # Output Freq en Hz
            self.ui.lcdNumber_2.display(freq)

            status = self.read_status()

            if status['fault']:
                self.ui.label_13.setText("⚠ Falla en el motor")
            elif not status['running']:
                self.ui.label_13.setText("Motor apagado")
            else:
                if status['direction'] == 'FWD':
                    self.ui.label_13.setText(f"Motor en marcha (Adelante) - {freq:.2f} Hz")
                elif status['direction'] == 'REV':
                    self.ui.label_13.setText(f"Motor en marcha (Reversa) - {freq:.2f} Hz")
                else:
                    self.ui.label_13.setText(f"Motor en marcha (Dirección desconocida) - {freq:.2f} Hz")

        except Exception as e:
            print("Error leyendo frecuencia:", e)
            self.ui.label_13.setText("Error de lectura")

    #––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # Manual Mode
    def on_manual_on(self):
        freq = self.ui.dial.value() 
        self.set_frequency(freq)

        if self.ui.radioButton.isChecked():
            self.command_start("FWD")
        elif self.ui.radioButton_2.isChecked():
            self.command_start("REV")
        else:
            print("⚠ Selecciona una dirección antes de iniciar")
            return

        self.ui.pushButton_4.setStyleSheet("background-color: #00d221;")
        self.ui.pushButton_5.setStyleSheet("background-color: rgb(170, 0, 0);")
        
    def on_manual_off(self):
        self.command_stop()
        self.ui.pushButton_5.setStyleSheet("background-color: #ff1f35;")
        self.ui.pushButton_4.setStyleSheet("background-color: rgb(0, 85, 0);")

    def on_dial_changed(self, value):
        self.set_frequency(value)
        self.ui.lcdNumber.display(value) 

    #––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
    # Automated Mode
    def load_configuration(self):
        path,_ = QFileDialog.getOpenFileName(self, "Abrir INI", "", "INI Files (*.ini)")
        if not path:
            return
        cfg = configparser.ConfigParser()
        cfg.read(path)
        self.automated_configs.clear()

        for sec in cfg.sections():
            raw_s = cfg[sec].get('speed', '').split(';')[0]
            raw_d = cfg[sec].get('direction', '').split(';')[0]
            raw_t = cfg[sec].get('duration', '').split(';')[0]
            speeds    = [int(x)   for x in raw_s.split(',') if x.strip()]
            dirs       = [x.strip()for x in raw_d.split(',') if x.strip()]
            durations  = [float(x) for x in raw_t.split(',') if x.strip()]
            self.automated_configs[sec] = {
                'speeds': speeds,
                'directions': dirs,
                'durations': durations
            }

        valid_keys = []
        invalid_keys = []
        for name, cfg_data in self.automated_configs.items():
            if cfg_data['speeds'] and max(cfg_data['speeds']) > MAX_FREQUENCY:
                invalid_keys.append(name)
            else:
                valid_keys.append(name)

        self.ui.comboBox.clear()
        for name in valid_keys:
            self.ui.comboBox.addItem(name)
        for name in invalid_keys:
            self.ui.comboBox.addItem(name)
            idx = self.ui.comboBox.count() - 1
            item = self.ui.comboBox.model().item(idx)
            if item:
                item.setEnabled(False)

        if invalid_keys:
            QMessageBox.warning(
                self, "Configuraciones ignoradas",
                "Se han encontrado configuraciones con velocidades > 70 Hz y han sido deshabilitadas:\n"
                + "\n".join(invalid_keys)
            )

    def delete_configuration(self):
        cur = self.ui.comboBox.currentText()
        if cur in self.automated_configs:
            del self.automated_configs[cur]
            self.ui.comboBox.removeItem(self.ui.comboBox.currentIndex())

    def apply_configuration(self):
        name = self.ui.comboBox.currentText()
        if name not in self.automated_configs:
            return
        cfg = self.automated_configs[name]
        s, durations = cfg['speeds'], cfg['durations']
        dirs = cfg['directions']
        if not (len(s) == len(dirs) == len(durations)):
            return
        self._set_automated_running(True)
        total = len(s); acc_ms = 0
        for i, (hz, dr, du) in enumerate(zip(s, dirs, durations), start=1):
            QTimer.singleShot(acc_ms, lambda h=hz, d=dr, step=i, tot=total: self._run_auto_step(h, d, step, tot))
            acc_ms += du * 1000
        QTimer.singleShot(int(acc_ms + 100), self._end_automated_sequence)

    def _run_auto_step(self, hz, direction, step, total):
        self.ui.LCD_INDICATOR.display(hz)
        self.ui.DIRECTION_AUTO.setText(direction)
        self.ui.STEP.setText(f"{step}/{total}")
        if direction == 'STOP':
            self.command_stop()
        else:
            self.set_frequency(hz)
            self.command_start(direction)
        self.ui.progressBar.setValue(int(step/total*100))

    def _end_automated_sequence(self):
        self._set_automated_running(False)

    def _set_automated_running(self, run: bool):
        for btn in (
            self.ui.pushButton, self.ui.pushButton_2, self.ui.pushButton_2,
            self.ui.pushButton_15, self.ui.pushButton_16, self.ui.pushButton_17
        ):
            btn.setEnabled(not run)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    sys.exit(app.exec())
