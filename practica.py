import tkinter as tk
from tkinter import messagebox
import serial
import time

# Configuración de la comunicación con Arduino
arduino = serial.Serial(port='COM3', baudrate=9600, timeout=1)  # Cambia COM3 por el puerto de tu Arduino

# Función para enviar datos al Arduino
def enviar_datos():
    try:
        rojo = int(entry_rojo.get())
        amarillo = int(entry_amarillo.get())
        verde = int(entry_verde.get())

        # Enviar datos al Arduino
        comando = f"{rojo},{amarillo},{verde}\n"  # Formato: rojo,amarillo,verde
        arduino.write(comando.encode())
        time.sleep(0.1)
        messagebox.showinfo("Éxito", "Datos enviados al Arduino")
    except ValueError:
        messagebox.showerror("Error", "Por favor ingresa valores numéricos válidos")

# Crear ventana de Tkinter
ventana = tk.Tk()
ventana.title("Control de Semáforo Doble")
ventana.geometry("400x300")

# Etiquetas y campos de entrada
tk.Label(ventana, text="Tiempo de luz roja (ms):").grid(row=0, column=0, padx=10, pady=10)
entry_rojo = tk.Entry(ventana)
entry_rojo.grid(row=0, column=1)

tk.Label(ventana, text="Tiempo de luz amarilla (ms):").grid(row=1, column=0, padx=10, pady=10)
entry_amarillo = tk.Entry(ventana)
entry_amarillo.grid(row=1, column=1)

tk.Label(ventana, text="Tiempo de luz verde (ms):").grid(row=2, column=0, padx=10, pady=10)
entry_verde = tk.Entry(ventana)
entry_verde.grid(row=2, column=1)

# Botón para enviar datos
btn_enviar = tk.Button(ventana, text="Enviar", command=enviar_datos)
btn_enviar.grid(row=3, column=0, columnspan=2, pady=20)

# Iniciar la ventana
ventana.mainloop()

# Cerrar conexión al salir
arduino.close()
