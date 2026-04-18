from __future__ import annotations

from app.providers.base import BaseProvider
from app.providers.bmw_provider import BmwProvider
from app.providers.gwm_provider import GwmProvider
from app.providers.generic_provider import GenericConfigProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {
            'bmw': BmwProvider(),
            'gwm': GwmProvider(),
            'tesla': GenericConfigProvider('tesla','Tesla','TESLA','Phase 1: offizieller Tesla-Fleet-API Provider vorbereitet. In dieser Version werden Hersteller-Maske und Konfiguration angelegt; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'client_id','label':'Client ID','type':'text','required':True},
                {'name':'client_secret','label':'Client Secret','type':'password','required':True},
                {'name':'refresh_token','label':'Refresh Token','type':'password','required':True},
                {'name':'vehicle_id','label':'Vehicle ID (optional)','type':'text','required':False},
            ], setup_steps=['Tesla Developer App / Fleet API vorbereiten.','Client-ID, Client-Secret und Refresh-Token hinterlegen.','MQTT- und Mapping-Integration folgt in einem nächsten Schritt.']),
            'volkswagen': GenericConfigProvider('volkswagen','Volkswagen','VW','Phase 1: VW-Konzern-Provider vorbereitet (CarConnectivity / WeConnect-Richtung). In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'spin','label':'S-PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ], setup_steps=['Volkswagen ID Zugangsdaten hinterlegen.']),
            'skoda': GenericConfigProvider('skoda','Skoda','SKODA','Phase 1: Skoda-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'spin','label':'S-PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ]),
            'seat': GenericConfigProvider('seat','SEAT','SEAT','Phase 1: SEAT-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'spin','label':'S-PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ]),
            'cupra': GenericConfigProvider('cupra','Cupra','CUPRA','Phase 1: Cupra-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'spin','label':'S-PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ]),
            'opel': GenericConfigProvider('opel','Opel','OPEL','Phase 1: Stellantis-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'vin','label':'VIN (optional)','type':'text','required':False},
            ]),
            'citroen': GenericConfigProvider('citroen','Citroën','CITROËN','Phase 1: Stellantis-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'vin','label':'VIN (optional)','type':'text','required':False},
            ]),
            'ds': GenericConfigProvider('ds','DS','DS','Phase 1: Stellantis-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'vin','label':'VIN (optional)','type':'text','required':False},
            ]),
            'peugeot': GenericConfigProvider('peugeot','Peugeot','PEUGEOT','Phase 1: Stellantis-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'country','label':'Land','type':'text','required':True,'default':'DE'},
                {'name':'vin','label':'VIN (optional)','type':'text','required':False},
            ]),
            'hyundai': GenericConfigProvider('hyundai','Hyundai','HYUNDAI','Phase 2: Hyundai-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'region','label':'Region','type':'text','required':True,'default':'EU'},
                {'name':'pin','label':'PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ]),
            'kia': GenericConfigProvider('kia','Kia','KIA','Phase 2: Kia-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'password','label':'Passwort','type':'password','required':True},
                {'name':'region','label':'Region','type':'text','required':True,'default':'EU'},
                {'name':'pin','label':'PIN (optional)','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ]),
            'mercedes': GenericConfigProvider('mercedes','Mercedes-Benz','MB','Phase 2: Mercedes-Provider vorbereitet. In dieser Version wird die Konfiguration vorbereitet; die Laufzeitintegration folgt.',[
                {'name':'account','label':'Benutzerkonto / E-Mail','type':'text','required':True},
                {'name':'client_id','label':'Client ID','type':'text','required':True},
                {'name':'client_secret','label':'Client Secret','type':'password','required':True},
                {'name':'refresh_token','label':'Refresh Token','type':'password','required':False},
                {'name':'vehicle_id','label':'Vehicle ID / VIN (optional)','type':'text','required':False},
            ], setup_steps=['Mercedes Developer/Fleet/API Zugang vorbereiten oder bestehende App-Credentials hinterlegen.']),
            'audi': GenericConfigProvider('audi','Audi','AUDI','Coming soon: Audi wird vorbereitet, die technische Richtung ist noch in Klärung.',[], setup_steps=['Kommt in einer späteren Version.'], category='Coming soon', auth_mode='coming_soon'),
            'byd': GenericConfigProvider('byd','BYD','BYD','Coming soon: BYD ist als Hersteller reserviert, die eigentliche Integration folgt später.',[], setup_steps=['Kommt in einer späteren Version.'], category='Coming soon', auth_mode='coming_soon'),
            'lucid': GenericConfigProvider('lucid','Lucid','LUCID','Coming soon: Lucid ist als Hersteller reserviert, die eigentliche Integration folgt später.',[], setup_steps=['Kommt in einer späteren Version.'], category='Coming soon', auth_mode='coming_soon'),
        }

    def all(self):
        return [provider.descriptor() for provider in self._providers.values()]

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f'Unbekannter Provider: {provider_id}')
        return self._providers[provider_id]
