#include "system_audio_capture.h"

#include <windows.h>

#include <audioclient.h>
#include <mmdeviceapi.h>
#include <wrl/client.h>

#include <flutter/standard_method_codec.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

namespace {

using Microsoft::WRL::ComPtr;

constexpr UINT32 kOutRate = 16000;
constexpr size_t kWavHeaderBytes = 44;
// Sem pacote por esse tempo, a origem deixa de segurar a mistura: a captura
// do som do computador simplesmente para de entregar quando nada esta tocando.
constexpr ULONGLONG kActiveWindowMs = 200;
constexpr int kPollMs = 20;
constexpr int kDeviceCheckEveryPolls = 50;
// Teto do que uma origem acumula esperando a outra, para relogios de placas
// diferentes nao fazerem a fila crescer durante uma reuniao longa.
constexpr size_t kMaxQueuedSamples = kOutRate * 2;

const GUID kSubtypePcm = {0x00000001, 0x0000, 0x0010,
                          {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};
const GUID kSubtypeFloat = {0x00000003, 0x0000, 0x0010,
                            {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};

std::wstring Utf16FromUtf8(const std::string& value) {
  if (value.empty()) return std::wstring();
  int size = ::MultiByteToWideChar(CP_UTF8, 0, value.data(),
                                   static_cast<int>(value.size()), nullptr, 0);
  std::wstring wide(size, L'\0');
  ::MultiByteToWideChar(CP_UTF8, 0, value.data(),
                        static_cast<int>(value.size()), wide.data(), size);
  return wide;
}

std::string StringArg(const flutter::EncodableMap* args, const char* key) {
  if (!args) return std::string();
  auto it = args->find(flutter::EncodableValue(key));
  if (it == args->end()) return std::string();
  const auto* value = std::get_if<std::string>(&it->second);
  return value ? *value : std::string();
}

// Uma origem de audio: a saida de som (em loopback) ou o microfone.
struct Source {
  bool loopback = false;
  ERole role = eConsole;
  // Microfone escolhido nas configuracoes. Vazio = padrao do sistema.
  std::wstring fixed_id;

  std::wstring opened_id;
  ComPtr<IAudioClient> client;
  ComPtr<IAudioCaptureClient> capture;

  UINT32 rate = 0;
  UINT32 channels = 0;
  UINT32 bits = 0;
  UINT32 block_align = 0;
  bool is_float = false;

  // Reamostragem para 16 kHz: media por janela ao reduzir, interpolacao
  // linear ao aumentar (fone Bluetooth em Hands-Free entrega 8 kHz).
  float acc = 0.0f;
  UINT32 acc_count = 0;
  UINT32 phase = 0;
  double position = 0.0;
  float previous = 0.0f;

  std::vector<float> queue;
  ULONGLONG last_packet_ms = 0;

  bool IsOpen() const { return capture != nullptr; }

  void Close() {
    if (client) client->Stop();
    capture.Reset();
    client.Reset();
    opened_id.clear();
  }

  bool Open(IMMDeviceEnumerator* enumerator, const std::wstring& device_id) {
    Close();
    ComPtr<IMMDevice> device;
    if (FAILED(enumerator->GetDevice(device_id.c_str(), &device))) return false;
    if (FAILED(device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
                                reinterpret_cast<void**>(
                                    client.ReleaseAndGetAddressOf())))) {
      return false;
    }

    WAVEFORMATEX* format = nullptr;
    if (FAILED(client->GetMixFormat(&format)) || !format) {
      Close();
      return false;
    }
    WORD tag = format->wFormatTag;
    if (tag == WAVE_FORMAT_EXTENSIBLE && format->cbSize >= 22) {
      const auto* extensible =
          reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(format);
      if (IsEqualGUID(extensible->SubFormat, kSubtypeFloat)) {
        tag = WAVE_FORMAT_IEEE_FLOAT;
      } else if (IsEqualGUID(extensible->SubFormat, kSubtypePcm)) {
        tag = WAVE_FORMAT_PCM;
      }
    }
    rate = format->nSamplesPerSec;
    channels = format->nChannels;
    bits = format->wBitsPerSample;
    block_align = format->nBlockAlign;
    is_float = tag == WAVE_FORMAT_IEEE_FLOAT && bits == 32;
    const bool is_pcm =
        tag == WAVE_FORMAT_PCM && (bits == 16 || bits == 24 || bits == 32);
    const bool usable = (is_float || is_pcm) && rate > 0 && channels > 0;

    HRESULT hr = E_FAIL;
    if (usable) {
      hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                              loopback ? AUDCLNT_STREAMFLAGS_LOOPBACK : 0,
                              2000000 /* 200 ms */, 0, format, nullptr);
    }
    ::CoTaskMemFree(format);
    if (FAILED(hr) ||
        FAILED(client->GetService(__uuidof(IAudioCaptureClient),
                                  reinterpret_cast<void**>(
                                      capture.ReleaseAndGetAddressOf()))) ||
        FAILED(client->Start())) {
      Close();
      return false;
    }

    acc = 0.0f;
    acc_count = 0;
    phase = 0;
    position = 0.0;
    previous = 0.0f;
    opened_id = device_id;
    return true;
  }

  float MonoFrame(const BYTE* frame) const {
    const UINT32 bytes = bits / 8;
    float sum = 0.0f;
    for (UINT32 channel = 0; channel < channels; ++channel) {
      const BYTE* sample = frame + channel * bytes;
      if (is_float) {
        float value;
        std::memcpy(&value, sample, sizeof(value));
        sum += value;
      } else if (bits == 16) {
        int16_t value;
        std::memcpy(&value, sample, sizeof(value));
        sum += value / 32768.0f;
      } else if (bits == 24) {
        int32_t value = (sample[0] << 8) | (sample[1] << 16) |
                        (static_cast<int32_t>(sample[2]) << 24);
        sum += (value >> 8) / 8388608.0f;
      } else {
        int32_t value;
        std::memcpy(&value, sample, sizeof(value));
        sum += value / 2147483648.0f;
      }
    }
    return sum / static_cast<float>(channels);
  }

  void Push(float sample) {
    if (rate >= kOutRate) {
      acc += sample;
      ++acc_count;
      phase += kOutRate;
      if (phase >= rate) {
        phase -= rate;
        queue.push_back(acc / static_cast<float>(acc_count));
        acc = 0.0f;
        acc_count = 0;
      }
      return;
    }
    const double step = static_cast<double>(rate) / kOutRate;
    while (position <= 0.0) {
      const float fraction = static_cast<float>(position + 1.0);
      queue.push_back(previous + (sample - previous) * fraction);
      position += step;
    }
    position -= 1.0;
    previous = sample;
  }

  // Le tudo o que a placa ja entregou. Falha (aparelho removido) fecha a
  // origem; quem a reabre e a verificacao periodica de dispositivos.
  void Read() {
    if (!IsOpen()) return;
    for (;;) {
      UINT32 packet = 0;
      if (FAILED(capture->GetNextPacketSize(&packet))) {
        Close();
        return;
      }
      if (packet == 0) return;

      BYTE* data = nullptr;
      UINT32 frames = 0;
      DWORD flags = 0;
      if (FAILED(capture->GetBuffer(&data, &frames, &flags, nullptr,
                                    nullptr))) {
        Close();
        return;
      }
      const bool silent = (flags & AUDCLNT_BUFFERFLAGS_SILENT) != 0 || !data;
      for (UINT32 index = 0; index < frames; ++index) {
        Push(silent ? 0.0f : MonoFrame(data + index * block_align));
      }
      if (frames > 0) last_packet_ms = ::GetTickCount64();
      capture->ReleaseBuffer(frames);
    }
  }
};

std::wstring DefaultDeviceId(IMMDeviceEnumerator* enumerator, EDataFlow flow,
                             ERole role) {
  ComPtr<IMMDevice> device;
  if (FAILED(enumerator->GetDefaultAudioEndpoint(flow, role, &device))) {
    return std::wstring();
  }
  LPWSTR id = nullptr;
  if (FAILED(device->GetId(&id)) || !id) return std::wstring();
  std::wstring value(id);
  ::CoTaskMemFree(id);
  return value;
}

void WriteWavHeader(FILE* file, uint32_t data_bytes) {
  const uint32_t byte_rate = kOutRate * 2;
  uint8_t header[kWavHeaderBytes];
  auto put32 = [&header](size_t at, uint32_t value) {
    std::memcpy(header + at, &value, sizeof(value));
  };
  auto put16 = [&header](size_t at, uint16_t value) {
    std::memcpy(header + at, &value, sizeof(value));
  };
  std::memcpy(header, "RIFF", 4);
  put32(4, 36 + data_bytes);
  std::memcpy(header + 8, "WAVEfmt ", 8);
  put32(16, 16);
  put16(20, 1);  // PCM
  put16(22, 1);  // mono
  put32(24, kOutRate);
  put32(28, byte_rate);
  put16(32, 2);
  put16(34, 16);
  std::memcpy(header + 36, "data", 4);
  put32(40, data_bytes);
  std::fseek(file, 0, SEEK_SET);
  std::fwrite(header, 1, sizeof(header), file);
}

}  // namespace

SystemAudioCapture::SystemAudioCapture(flutter::BinaryMessenger* messenger) {
  channel_ = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      messenger, "intarq/system_audio",
      &flutter::StandardMethodCodec::GetInstance());
  channel_->SetMethodCallHandler([this](const auto& call, auto result) {
    HandleMethodCall(call, std::move(result));
  });
}

SystemAudioCapture::~SystemAudioCapture() {
  channel_->SetMethodCallHandler(nullptr);
  StopThread();
  std::lock_guard<std::mutex> lock(chunk_mutex_);
  CloseChunk();
}

void SystemAudioCapture::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue>& call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  const auto* args = std::get_if<flutter::EncodableMap>(call.arguments());
  const std::string& method = call.method_name();

  if (method == "start") {
    const std::string path = StringArg(args, "path");
    if (path.empty()) {
      result->Error("bad_args", "Caminho do arquivo ausente.");
      return;
    }
    std::string error;
    if (!Start(path, StringArg(args, "micDeviceId"), &error)) {
      result->Error("start_failed", error);
      return;
    }
    result->Success();
  } else if (method == "rotate") {
    const std::string path = StringArg(args, "path");
    if (path.empty() || !thread_.joinable()) {
      result->Error("not_recording", "Nenhuma gravacao em andamento.");
      return;
    }
    std::lock_guard<std::mutex> lock(chunk_mutex_);
    flutter::EncodableValue finished = CloseChunk();
    if (!OpenChunk(path)) {
      result->Error("file_failed", "Nao foi possivel criar o arquivo do bloco.");
      return;
    }
    result->Success(finished);
  } else if (method == "stop") {
    StopThread();
    std::lock_guard<std::mutex> lock(chunk_mutex_);
    result->Success(CloseChunk());
  } else {
    result->NotImplemented();
  }
}

bool SystemAudioCapture::Start(const std::string& path,
                               const std::string& mic_device_id,
                               std::string* error) {
  if (thread_.joinable()) {
    *error = "Ja existe uma gravacao do som do computador em andamento.";
    return false;
  }
  {
    std::lock_guard<std::mutex> lock(chunk_mutex_);
    if (!OpenChunk(path)) {
      *error = "Nao foi possivel criar o arquivo do bloco.";
      return false;
    }
  }

  // 0 = abrindo, 1 = gravando, -1 = falhou.
  std::atomic<int> init_state{0};
  std::string init_error;
  stop_requested_ = false;
  thread_ = std::thread(&SystemAudioCapture::CaptureLoop, this,
                        Utf16FromUtf8(mic_device_id), &init_error, &init_state);
  while (init_state.load() == 0) ::Sleep(5);
  if (init_state.load() < 0) {
    thread_.join();
    std::lock_guard<std::mutex> lock(chunk_mutex_);
    CloseChunk();
    ::DeleteFileW(Utf16FromUtf8(path).c_str());
    *error = init_error;
    return false;
  }
  return true;
}

void SystemAudioCapture::StopThread() {
  if (!thread_.joinable()) return;
  stop_requested_ = true;
  thread_.join();
}

void SystemAudioCapture::CaptureLoop(std::wstring mic_device_id,
                                     std::string* init_error,
                                     std::atomic<int>* init_state) {
  const HRESULT com = ::CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  {
    ComPtr<IMMDeviceEnumerator> enumerator;
    if (FAILED(::CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr,
                                  CLSCTX_ALL, IID_PPV_ARGS(&enumerator)))) {
      *init_error = "Servico de audio do Windows indisponivel.";
      init_state->store(-1);
      if (SUCCEEDED(com)) ::CoUninitialize();
      return;
    }

    // Duas saidas: a padrao e a de comunicacao. O Teams costuma tocar na
    // segunda, e as duas so coincidem quando o usuario nunca as separou.
    Source sources[3];
    Source& console = sources[0];
    Source& communications = sources[1];
    Source& mic = sources[2];
    console.loopback = true;
    communications.loopback = true;
    communications.role = eCommunications;
    mic.fixed_id = mic_device_id;

    // Reabre o que mudou: fone conectado no meio da reuniao troca a saida
    // padrao sem invalidar a antiga, que so passaria a entregar silencio.
    auto sync_devices = [&]() {
      const std::wstring console_id =
          DefaultDeviceId(enumerator.Get(), eRender, eConsole);
      std::wstring communications_id =
          DefaultDeviceId(enumerator.Get(), eRender, eCommunications);
      if (communications_id == console_id) communications_id.clear();
      const std::wstring mic_id =
          mic.fixed_id.empty()
              ? DefaultDeviceId(enumerator.Get(), eCapture, eConsole)
              : mic.fixed_id;

      const std::wstring* wanted[3] = {&console_id, &communications_id,
                                       &mic_id};
      for (int index = 0; index < 3; ++index) {
        Source& source = sources[index];
        if (source.opened_id == *wanted[index] && source.IsOpen()) continue;
        if (wanted[index]->empty()) {
          source.Close();
        } else {
          source.Open(enumerator.Get(), *wanted[index]);
        }
      }
    };

    sync_devices();
    if (!console.IsOpen() && !communications.IsOpen()) {
      *init_error =
          "Nao foi possivel capturar o som do computador: nenhuma saida de "
          "audio ativa.";
      init_state->store(-1);
      for (Source& source : sources) source.Close();
      enumerator.Reset();
      if (SUCCEEDED(com)) ::CoUninitialize();
      return;
    }
    init_state->store(1);
    // A partir daqui `init_error` e `init_state` nao existem mais: sao da
    // pilha de quem chamou Start.

    std::vector<float> mix;
    int polls = 0;
    bool last_pass = false;
    while (!last_pass) {
      last_pass = stop_requested_.load();
      if (!last_pass) ::Sleep(kPollMs);
      if (++polls >= kDeviceCheckEveryPolls) {
        polls = 0;
        sync_devices();
      }

      const ULONGLONG now = ::GetTickCount64();
      size_t count = SIZE_MAX;
      size_t longest = 0;
      bool any_active = false;
      for (Source& source : sources) {
        source.Read();
        longest = std::max(longest, source.queue.size());
        if (source.IsOpen() && now - source.last_packet_ms < kActiveWindowMs) {
          any_active = true;
          count = std::min(count, source.queue.size());
        }
      }
      // Na ultima passada, e quando ninguem esta entregando, escoa o que
      // sobrou nas filas em vez de esperar por uma origem que nao vem.
      if (!any_active || last_pass) count = longest;
      if (count == 0) continue;

      mix.assign(count, 0.0f);
      float system_peak = 0.0f;
      float mic_peak = 0.0f;
      for (Source& source : sources) {
        const size_t take = std::min(count, source.queue.size());
        float peak = 0.0f;
        for (size_t index = 0; index < take; ++index) {
          const float sample = source.queue[index];
          mix[index] += sample;
          peak = std::max(peak, std::fabs(sample));
        }
        source.queue.erase(source.queue.begin(), source.queue.begin() + take);
        if (source.queue.size() > kMaxQueuedSamples) {
          source.queue.erase(
              source.queue.begin(),
              source.queue.end() - static_cast<ptrdiff_t>(kMaxQueuedSamples));
        }
        if (source.loopback) {
          system_peak = std::max(system_peak, peak);
        } else {
          mic_peak = std::max(mic_peak, peak);
        }
      }
      WriteMix(mix.data(), mix.size(), system_peak, mic_peak);
    }

    for (Source& source : sources) source.Close();
  }
  if (SUCCEEDED(com)) ::CoUninitialize();
}

bool SystemAudioCapture::OpenChunk(const std::string& path) {
  FILE* file = nullptr;
  if (_wfopen_s(&file, Utf16FromUtf8(path).c_str(), L"wb") != 0 || !file) {
    return false;
  }
  WriteWavHeader(file, 0);
  chunk_ = Chunk();
  chunk_.file = file;
  chunk_.path = path;
  return true;
}

flutter::EncodableValue SystemAudioCapture::CloseChunk() {
  if (!chunk_.file) return flutter::EncodableValue();
  WriteWavHeader(chunk_.file, chunk_.data_bytes);
  std::fclose(chunk_.file);
  flutter::EncodableMap info = {
      {flutter::EncodableValue("path"), flutter::EncodableValue(chunk_.path)},
      {flutter::EncodableValue("systemPeak"),
       flutter::EncodableValue(static_cast<double>(chunk_.system_peak))},
      {flutter::EncodableValue("micPeak"),
       flutter::EncodableValue(static_cast<double>(chunk_.mic_peak))},
  };
  chunk_ = Chunk();
  return flutter::EncodableValue(info);
}

void SystemAudioCapture::WriteMix(const float* samples, size_t count,
                                  float system_peak, float mic_peak) {
  std::vector<int16_t> pcm(count);
  for (size_t index = 0; index < count; ++index) {
    const float clamped = std::max(-1.0f, std::min(1.0f, samples[index]));
    pcm[index] = static_cast<int16_t>(std::lround(clamped * 32767.0f));
  }
  std::lock_guard<std::mutex> lock(chunk_mutex_);
  if (!chunk_.file) return;
  const size_t written =
      std::fwrite(pcm.data(), sizeof(int16_t), count, chunk_.file);
  chunk_.data_bytes += static_cast<uint32_t>(written * sizeof(int16_t));
  chunk_.system_peak = std::max(chunk_.system_peak, system_peak);
  chunk_.mic_peak = std::max(chunk_.mic_peak, mic_peak);
}
