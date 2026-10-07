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

LEGAL_LAST_UPDATED = "October 6, 2026"

TERMS_OF_SERVICE = f"""Last updated: {LEGAL_LAST_UPDATED}

1. Acceptance of Terms
By installing or using SolarQuote ("the App"), you agree to these Terms of Service. If you do not agree, do not use the App.

2. What the App Does
SolarQuote is a tool for solar installers to size systems, run financial projections, and generate client-facing proposals (PDF, Excel, CSV, and PowerPoint). All calculations happen on your device, and the App never sends your client or project data to any SumClarTech server. Date checks and Google Play purchases use a network connection. A deployment may also use an explicitly configured subscription verification service; see the Privacy Policy.

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
SolarQuote sizes systems, simulates energy flows, and creates proposals on your device. Core quote calculations work offline. This policy describes local storage, user-directed copies, and subscription-related connections.

2. Information Stored on Your Device
Saved projects and recoverable drafts include client name, contact number, email, location/site inputs, energy usage, tariff, equipment selections, and quote assumptions. SolarQuote stores them in its local database. Your device's users and anyone with access to its storage or backups may be able to read this information; secure your device appropriately.

3. Exported Reports and Backups
Reports are stored in the app's report folder. You can view them, save a copy to a location you choose, or share/email them using another app. Project backup files contain client and project information. Choosing a cloud location or sharing service may send that copy to its provider. No report, backup, or email is sent automatically by SolarQuote.

4. Developer Access and Analytics
SolarQuote contains no advertising or analytics SDK. Quote information is not sent to a developer server by its calculation or export features. Subscription verification, if configured, sends subscription information as described below; it does not include your client projects.

5. Network Connections
Date verification requests the current date from worldtimeapi.org. Like any network request, the time-service operator can see connection metadata such as your IP address. The request does not contain your client/project data.
Google Play handles purchases, payment details, offers, and subscription status under Google's policies.
An optional solar-resource lookup contacts NASA POWER only when you request it. It sends site latitude/longitude to retrieve solar-resource data; it does not send client names, email, phone numbers, or address text. Coordinates can reveal a site location. Roof tilt, orientation, and shading adjustments are calculated locally. Cached resource data can be used offline.
If a subscription verification service is configured for a deployment, SolarQuote sends the Google Play purchase token and product/package identifiers to that service over HTTPS. Its operator uses these to verify subscription access with Google. It does not receive client/project information. Consult the deployment operator about retention of subscription verification data.
User-chosen share, email, cloud-save, and backup destinations have their own privacy practices.

6. Deletion and Copies
Deleting a saved project removes its database record; it does not remove previously exported reports or copies shared/saved elsewhere. Report History lets you delete individual copies in the app's report folder. Uninstalling normally removes app-managed local storage. External copies, exported backups, device/vendor backups, and recipients' copies may remain. SolarQuote cannot delete those copies for you.
This Android build disables automatic application backup in its manifest. Device transfer and vendor behavior vary; do not treat uninstall or deletion as a guarantee that every copy has been erased.

7. Your Client Information
You decide what client information to collect, who may access it, how long to keep it, and when to share it. Obtain any necessary permissions and provide appropriate disclosures for your business. This policy does not establish your legal role or certify compliance with privacy law.

8. Children
SolarQuote is designed as a professional tool for solar installers. Its core features do not collect information through developer accounts.

9. Changes and Contact
Updates to this policy are shown by the date above. Questions may be sent to {CONTACT_EMAIL}."""


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
