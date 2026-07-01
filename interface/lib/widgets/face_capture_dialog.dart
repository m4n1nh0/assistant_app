import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import '../utils/theme.dart';

class FaceCaptureDialog extends StatefulWidget {
  final String title;
  final String actionLabel;

  const FaceCaptureDialog({
    super.key,
    required this.title,
    this.actionLabel = 'CAPTURAR',
  });

  @override
  State<FaceCaptureDialog> createState() => _FaceCaptureDialogState();
}

class _FaceCaptureDialogState extends State<FaceCaptureDialog> {
  CameraController? _controller;
  String _status = 'Inicializando câmera...';
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _initCamera();
  }

  Future<void> _initCamera() async {
    try {
      final cameras = await availableCameras();
      final camera = cameras.firstWhere(
        (item) => item.lensDirection == CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        camera,
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );
      await controller.initialize();
      if (!mounted) return;
      setState(() {
        _controller = controller;
        _status = 'Centralize o rosto e mantenha boa iluminação.';
        _busy = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _status = 'Não foi possível abrir a câmera: $e';
        _busy = false;
      });
    }
  }

  Future<void> _capture() async {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized || _busy) return;
    setState(() {
      _busy = true;
      _status = 'Capturando...';
    });
    try {
      final file = await controller.takePicture();
      final bytes = await file.readAsBytes();
      if (mounted) Navigator.of(context).pop(bytes);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _status = 'Falha na captura: $e';
        _busy = false;
      });
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;

    return Dialog(
      backgroundColor: AssistantTheme.surface,
      child: Container(
        width: 460,
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          border: Border.all(color: AssistantTheme.border2),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              widget.title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'Rajdhani',
                fontSize: 18,
                fontWeight: FontWeight.w800,
                letterSpacing: 4,
                color: AssistantTheme.c1,
              ),
            ),
            const SizedBox(height: 14),
            AspectRatio(
              aspectRatio: 4 / 3,
              child: Container(
                color: AssistantTheme.bg,
                child: controller != null && controller.value.isInitialized
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(4),
                        child: CameraPreview(controller),
                      )
                    : Center(
                        child: _busy
                            ? const CircularProgressIndicator()
                            : const Icon(Icons.no_photography_outlined,
                                color: AssistantTheme.textMuted, size: 42),
                      ),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              _status,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontFamily: 'JetBrains Mono',
                fontSize: 10,
                color: AssistantTheme.textSecondary,
              ),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('CANCELAR'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: ElevatedButton(
                    onPressed: _busy || controller == null ? null : _capture,
                    child: Text(widget.actionLabel),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
