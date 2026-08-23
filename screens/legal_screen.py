"""Terms of Service and Privacy Policy screens, reached from About > Legal.

Full screens rather than dialogs: KivyMD's MDDialog hides its internal
scrollbar (bar_width is forced to 0 in kivymd/uix/dialog/dialog.py), so a
document long enough to need scrolling gave no visual cue that there was more
below the fold. A plain ScrollView -- the same one every other screen in this
app already uses -- shows its scrollbar and matches the rest of the app's
navigation (header + back arrow) instead of stretching a popup meant for short
confirmations into a legal-document reader.
"""

from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen

from screens.about_screen import CONTACT_EMAIL
from ui_style import ON_SURFACE, screen_header

LEGAL_LAST_UPDATED = "August 23, 2026"

TERMS_OF_SERVICE = f"""Last updated: {LEGAL_LAST_UPDATED}

1. Acceptance of Terms
By installing or using SolarQuote ("the App"), you agree to these Terms of Service. If you do not agree, do not use the App.

2. What the App Does
SolarQuote is an offline tool for solar installers to size systems, run financial projections, and generate client-facing proposals (PDF, Excel, CSV, and PowerPoint). All calculations happen on your device; the App does not connect to the internet or to any SumClarTech server.

3. Estimates Only, No Warranty
Every figure the App produces -- sizing, savings, ROI, and payback -- is an engineering estimate based on the information and assumptions you provide. Actual solar production, electricity consumption, weather conditions, equipment specifications, installation conditions, and utility requirements may differ. Final system designs must be verified and signed off by a qualified solar or electrical professional before being presented as final to a client. SumClarTech makes no warranty, express or implied, as to the accuracy, completeness, or fitness of any output for a particular purpose.

4. Your Responsibilities
You are responsible for the accuracy of the client and project information you enter, for reviewing generated reports before sharing them, and for complying with any professional, licensing, or regulatory obligations that apply to your solar installation business in your jurisdiction.

5. Your Data
Client and project information you enter stays stored locally on your device. You own that data and are responsible for keeping your device secure and for backing it up if needed -- see the Privacy Policy for details on what is stored and how to delete it.

6. Intellectual Property
The App, its design, and its underlying code are owned by SumClarTech. Nothing in these Terms transfers ownership of the App to you; you're granted a personal, non-exclusive license to use it for your business.

7. Limitation of Liability
To the maximum extent permitted by law, SumClarTech is not liable for any indirect, incidental, or consequential damages arising from your use of the App, including decisions made or proposals issued based on its output.

8. Changes to These Terms
These Terms may be updated from time to time. Continued use of the App after an update means you accept the revised Terms.

9. Governing Law
These Terms are governed by the laws of the Republic of the Philippines, without regard to its conflict-of-law principles. Any dispute arising from these Terms or your use of the App will be subject to the exclusive jurisdiction of the courts of the Philippines.

10. Contact
Questions about these Terms can be sent to {CONTACT_EMAIL}."""

PRIVACY_POLICY = f"""Last updated: {LEGAL_LAST_UPDATED}

1. Overview
SolarQuote is built to work fully offline. This policy explains what information the App stores and, just as importantly, what it does not do with it.

2. Information Stored on Your Device
When you create a client project, the App stores what you enter -- client name, contact number, email, project location, notes, energy usage, tariff, and the resulting system-design and simulation figures -- in a local database inside the App's private storage on your device. This information never leaves your device unless you choose to share it (see below).

3. Exported Reports
PDF, Excel, CSV, and PowerPoint proposals you export are saved to the App's own folder on your device. They are only shared, emailed, or sent anywhere if you actively choose to using the App's Share or Email to Client buttons, which hand the file to your own device's apps (your email client, messaging apps, etc.) -- SumClarTech does not receive a copy.

4. No Data Collection by Us
The App has no server, no user accounts, no analytics, no advertising, and no third-party tracking SDKs. SumClarTech does not collect, receive, or have access to any client information, project data, or exported files you create in the App.

5. Data Control and Deletion
You can delete any saved project from within the App at any time. Uninstalling the App permanently deletes its local database and all exported files stored in its folder from your device.

6. Third-Party Services
The App does not integrate with any third-party analytics, advertising, or cloud services.

7. Children's Privacy
The App is a professional tool for solar installers and is not directed at children. SumClarTech does not knowingly collect information from children.

8. Your Role as the Data Controller
The client information you enter (name, contact number, email, and project location) is your own client's personal data, collected by you in the course of your business. Because the App stores this data only on your device and never transmits it to SumClarTech, you -- not SumClarTech -- act as the data controller for that information under the Philippines' Data Privacy Act of 2012 (Republic Act No. 10173), and are responsible for handling it in accordance with that law, including obtaining any consent from your clients that it requires.

9. Changes to This Policy
This policy may be updated from time to time to reflect changes in the App. The "Last updated" date above will reflect the most recent revision.

10. Contact
Questions about this Privacy Policy can be sent to {CONTACT_EMAIL}."""


class _LegalScreen(MDScreen):
    """Base for a full-screen scrollable legal document. Subclasses set
    `screen_name`, `title`, and `body` as class attributes."""

    screen_name = ""
    title = ""
    body = ""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = self.screen_name
        self._build_ui()

    def _build_ui(self) -> None:
        root = MDBoxLayout(orientation="vertical")
        root.add_widget(screen_header(self.title, step=None, on_back=self._go_back))

        scroll = ScrollView()
        content = MDBoxLayout(orientation="vertical", padding=dp(16), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        label = MDLabel(
            text=self.body, theme_text_color="Custom", text_color=ON_SURFACE, size_hint_y=None,
        )
        label.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))
        label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
        content.add_widget(label)

        scroll.add_widget(content)
        root.add_widget(scroll)
        self.add_widget(root)

    def _go_back(self) -> None:
        MDApp.get_running_app().root.current = "about"


class TermsScreen(_LegalScreen):
    screen_name = "terms"
    title = "Terms of Service"
    body = TERMS_OF_SERVICE


class PrivacyScreen(_LegalScreen):
    screen_name = "privacy"
    title = "Privacy Policy"
    body = PRIVACY_POLICY
