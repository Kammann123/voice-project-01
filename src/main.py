# Custom Libraries
import vocoder
import synthesizer

# Third-Party Libraries
import pyaudio
import numpy as np
import mido

# Native-Python Libraries
import queue

def on_output_frame(in_data, frame_count, time_info, status):
    global output_queue
    if output_queue.empty() == True:
        buffer = np.zeros((FRAME_SIZE), dtype=np.float32)
    else:
        buffer = output_queue.get()
    return (buffer.astype(np.float32).tobytes(), pyaudio.paContinue)

def on_input_frame(in_data, frame_count, time_info, status):
    voice_queue.put(np.frombuffer(in_data, dtype=np.float32))
    return (in_data, pyaudio.paContinue)

# Parameters needed to configure the streams
SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_WIDTH_IN_BYTES = 4
ORDER = 48
FRAME_TIME = 60e-3                              # Audio Buffer Duration
FRAME_SIZE = int(FRAME_TIME * SAMPLE_RATE)
WINDOW_TIME = 20e-3                              # Vocoder Processing Duration
WINDOW_SIZE = int(WINDOW_TIME * SAMPLE_RATE)
PRE_EMPHASIS = 0.97
VOICE_THRESHOLD_dB = -40

# Initializations
p = pyaudio.PyAudio()                                               # PyAudio Instance
v = vocoder.Vocoder(WINDOW_SIZE, ORDER, PRE_EMPHASIS)               # Vocoder Instance
s = synthesizer.Synthesizer(FRAME_SIZE, SAMPLE_RATE)                # Synthesizer Instance

# Create the needed queues
voice_queue = queue.Queue()
output_queue = queue.Queue()
excitation_queue = queue.Queue()

# Fetch devices' information and parameters from the PyAudio API, we can select
# to use the default input/output devices or allow the user to choose some of the 
# other available devices
devices_count = p.get_device_count()
devices_info = [p.get_device_info_by_index(i) for i in range(devices_count)]
default_input_device = p.get_default_input_device_info()
default_output_device = p.get_default_output_device_info()

# Choose a specific input device and create a stream to start reading
# audio samples from it, using the non-blocking method (callback)
selected_input_device = default_input_device
input_stream = p.open(
    rate=SAMPLE_RATE,
    channels=CHANNELS,
    format=p.get_format_from_width(SAMPLE_WIDTH_IN_BYTES),
    input=True,
    output=False,
    frames_per_buffer=FRAME_SIZE,
    input_device_index=default_input_device['index'],
    stream_callback=on_input_frame
)

# Choose a specific output device and create a stream to start sending
# audio samples to it, using the non-blocking method (callback)
selected_output_device = default_output_device
output_stream = p.open(
    rate=SAMPLE_RATE,
    channels=CHANNELS,
    format=pyaudio.paFloat32,
    input=False,
    output=True,
    frames_per_buffer=FRAME_SIZE,
    output_device_index=default_output_device['index'],
    stream_callback=on_output_frame
)

# Using the MIDO library we can get what MIDI inputs are connected to the
# system and use any of them to open a MIDI connection.
input_devices = mido.get_input_names()
input_port = mido.open_input()

# Initialize the output queue
output_queue.put(np.zeros((FRAME_SIZE), dtype=np.float32))

# Start the synthesizer
s.set_frequency(0.0)
s.set_amplitude(0.0)

# Start the streams
input_stream.start_stream()
output_stream.start_stream()

while True:
    try:
        if voice_queue.empty() == False and excitation_queue.empty() == False:
            voice_frame = voice_queue.get()
            excitation = excitation_queue.get()
            output_frame = np.zeros(voice_frame.shape, dtype=np.float32)
            voice_windows = np.split(voice_frame, FRAME_SIZE // WINDOW_SIZE)
            excitation_windows = np.split(excitation, FRAME_SIZE // WINDOW_SIZE)
            for index, voice_window in enumerate(voice_windows):
                voice_level = voice_window.std()
                voice_level_dB = 20 * np.log10(voice_level)
                excitation_window = excitation_windows[index] if voice_level_dB > VOICE_THRESHOLD_dB else np.zeros(WINDOW_SIZE)
                output_window = v.process_frame(
                    voice_window,
                    #np.random.normal(0, 0.03, size=WINDOW_SIZE),
                    excitation_window,
                )
                output_frame[index * WINDOW_SIZE:(index + 1) * WINDOW_SIZE] = output_window
            output_queue.put(output_frame)
        elif excitation_queue.empty() == True:
            generated_frame = s.generate_frame()
            excitation_queue.put(generated_frame)
            
        for message in input_port.iter_pending():
            if message.type == 'note_on':
                s.set_frequency(440 * (2**((message.note - 69) / 12)))
                s.set_amplitude(0.008)
            elif message.type == 'note_off':
                s.set_frequency(0.0)
                s.set_amplitude(0.0)
                
    except KeyboardInterrupt:
        break

# Close streams
input_stream.stop_stream()
input_stream.close()
output_stream.stop_stream()
output_stream.close()

# Clean up the resources taken from the system by PyAudio
p.terminate()