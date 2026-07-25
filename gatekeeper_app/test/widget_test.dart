import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/main.dart';

void main() {
  testWidgets('SmartKeyApp widget smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const SmartKeyApp());
    expect(find.byType(SmartKeyApp), findsOneWidget);
  });
}
