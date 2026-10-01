#ifndef RUNNER_SYSTEM_AUDIO_CAPTURE_H_
#define RUNNER_SYSTEM_AUDIO_CAPTURE_H_

#include <flutter/binary_messenger.h>
#include <flutter/encodable_value.h>
#include <flutter/method_channel.h>

#include <atomic>
#include <cstdio>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

// Grava o som que o computador esta tocando somado ao microfone, para
// registrar uma reuniao online (Meet, Teams) inteira: o que os outros dizem
// sai pelo alto-falante e nunca passa pelo microfone.
//
// A saida e o mesmo WAV de 16 kHz mono que a gravacao por microfone produz, em
// blocos: `rotate` troca o arquivo sem parar a captura, para nao perder a fala
// que acontece enquanto o bloco anterior sobe para o backend.
//
// Canal `intarq/system_audio`:
//   start  {path, micDeviceId}  -> null
//   rotate {path}               -> {path, systemPeak, micPeak}
//   stop                        -> {path, systemPeak, micPeak} | null
class SystemAudioCapture {
 public:
  explicit SystemAudioCapture(flutter::BinaryMessenger* messenger);
  ~SystemAudioCapture();

  SystemAudioCapture(const SystemAudioCapture&) = delete;
  SystemAudioCapture& operator=(const SystemAudioCapture&) = delete;

 private:
  // Arquivo do bloco em gravacao, com o pico de cada origem. O pico e o que
  // permite avisar que a reuniao esta tocando em outra saida de som.
  struct Chunk {
    FILE* file = nullptr;
    std::string path;
    uint32_t data_bytes = 0;
    float system_peak = 0.0f;
    float mic_peak = 0.0f;
  };

  void HandleMethodCall(
      const flutter::MethodCall<flutter::EncodableValue>& call,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);

  bool Start(const std::string& path, const std::string& mic_device_id,
             std::string* error);
  void StopThread();
  void CaptureLoop(std::wstring mic_device_id, std::string* init_error,
                   std::atomic<int>* init_state);

  bool OpenChunk(const std::string& path);
  // Fecha o bloco atual e devolve o que ele registrou. Exige `chunk_mutex_`.
  flutter::EncodableValue CloseChunk();
  void WriteMix(const float* samples, size_t count, float system_peak,
                float mic_peak);

  std::unique_ptr<flutter::MethodChannel<flutter::EncodableValue>> channel_;
  std::thread thread_;
  std::atomic<bool> stop_requested_{false};
  std::mutex chunk_mutex_;
  Chunk chunk_;
};

#endif  // RUNNER_SYSTEM_AUDIO_CAPTURE_H_
