import 'package:flutter_test/flutter_test.dart';
import 'package:assistant_app/services/api_service.dart';

void main() {
  test('parses administrative registration requirements', () {
    final status = AuthSetupStatus.fromJson({
      'needs_setup': true,
      'invite_registration_enabled': true,
      'registration_requires_token': true,
      'registration_delivery_configured': true,
      'admin_email_hint': 'ad***@example.com',
    });

    expect(status.needsSetup, isTrue);
    expect(status.inviteRegistrationEnabled, isTrue);
    expect(status.registrationRequiresToken, isTrue);
    expect(status.registrationDeliveryConfigured, isTrue);
    expect(status.adminEmailHint, 'ad***@example.com');
  });
}
