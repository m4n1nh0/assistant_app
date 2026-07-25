import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AssistantTheme {
  static const bg = Color(0xFF07090E);
  static const bg2 = Color(0xFF0C1018);
  static const surface = Color(0xFF111827);
  static const surface2 = Color(0xFF1A2335);
  static const border = Color(0xFF1E2D45);
  static const border2 = Color(0xFF263650);

  static const c1 = Color(0xFF38BDF8);
  static const c2 = Color(0xFFA78BFA);
  static const c3 = Color(0xFF34D399);
  static const c4 = Color(0xFFFB923C);
  static const c5 = Color(0xFFF472B6);
  static const cHF = Color(0xFFFBBF24);

  static const textPrimary = Color(0xFFE2EAF5);
  static const textSecondary = Color(0xFF8BA3BE);
  static const textMuted = Color(0xFF3D5A73);
  static const danger = Color(0xFFF87171);

  static const llmColors = {
    'backend': c1,
    'claude': c4,
    'gpt': c3,
    'together': c1,
    'openrouter': c2,
    'deepseek': cHF,
    'gemini': c1,
    'grok': c5,
    'localai': c3,
    'llama': c2,
    'hf': cHF,
  };

  static ThemeData get darkTheme => ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: bg,
        colorScheme: const ColorScheme.dark(
          primary: c1,
          secondary: c2,
          surface: surface,
          error: danger,
        ),
        textTheme: GoogleFonts.rajdhaniTextTheme(
          ThemeData.dark().textTheme,
        ).copyWith(
          displayLarge: _mono(28, FontWeight.w700, textPrimary),
          displayMedium: _mono(22, FontWeight.w700, textPrimary),
          displaySmall: _mono(18, FontWeight.w600, textPrimary),
          headlineMedium: _rajdhani(20, FontWeight.w700, textPrimary),
          headlineSmall: _rajdhani(16, FontWeight.w600, textPrimary),
          titleLarge: _rajdhani(14, FontWeight.w600, textSecondary),
          titleMedium: _mono(13, FontWeight.w400, textPrimary),
          bodyLarge: _mono(13, FontWeight.w400, textPrimary),
          bodyMedium: _mono(12, FontWeight.w400, textSecondary),
          bodySmall: _mono(10, FontWeight.w400, textMuted),
          labelLarge: _rajdhani(12, FontWeight.w600, c1),
          labelSmall: _mono(9, FontWeight.w400, textMuted),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: surface,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: border),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: border),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(4),
            borderSide: const BorderSide(color: c1, width: 1.5),
          ),
          hintStyle: _mono(12, FontWeight.w400, textMuted),
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: surface2,
            foregroundColor: c1,
            side: const BorderSide(color: border2),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(4)),
            textStyle: _rajdhani(13, FontWeight.w600, c1),
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          ),
        ),
        dividerColor: border,
      );

  static TextStyle _mono(double size, FontWeight w, Color c) =>
      GoogleFonts.jetBrainsMono(fontSize: size, fontWeight: w, color: c);

  static TextStyle _rajdhani(double size, FontWeight w, Color c) =>
      GoogleFonts.rajdhani(fontSize: size, fontWeight: w, color: c);
}

BoxDecoration glowDecoration({
  Color color = AssistantTheme.c1,
  double radius = 4,
  double opacity = 0.25,
  double blurRadius = 20,
}) =>
    BoxDecoration(
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: color.withOpacity(0.4), width: 1),
      boxShadow: [
        BoxShadow(color: color.withOpacity(opacity), blurRadius: blurRadius)
      ],
    );
