from __future__ import unicode_literals

import time
import json
import requests
import calendar

from random import uniform
from operator import itemgetter, methodcaller
from datetime import datetime
from pokemongo_bot import inventory
from pokemongo_bot.base_task import BaseTask
from pokemongo_bot.inventory import Pokemons
from pokemongo_bot.worker_result import WorkerResult
from pokemongo_bot.cell_workers.pokemon_catch_worker import PokemonCatchWorker

# Represents a URL source and its mappings
class SniperSource(object):
    def __init__(self, data):
        self.url = data.get('url', '')
        self.key = data.get('key', '')
        self.timeout = data.get('timeout', 5)
        self.enabled = data.get('enabled', False)
        self.time_mask = data.get('time_mask', '%Y-%m-%d %H:%M:%S')
        self.mappings = SniperSourceMapping(data.get('mappings', {}))

    def __str__(self):
        return self.url

    def fetch_raw(self):
        some_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/52.0.2743.116 Safari/537.36'
        response = requests.get(self.url, headers={'User-Agent': some_agent}, timeout=self.timeout)
        results = response.json()

        # If the results is a dict, retrieve the list from it by the given key. This will return a list afterall.
        if isinstance(results, dict):
            results = results.get(self.key, [])

        # If results is STILL a dict (eg. each pokemon is its own dict), need to build data from nested json (example whereispokemon.net)
        while isinstance(results,dict):
            tmpResults = []
            for key, value in results.iteritems():
                tmpResults.append(value)
                results = tmpResults
                
        return results

    def fetch(self):
        pokemons = []

        try:
            results = self.fetch_raw()

            # Parse results
            for result in results:
                iv = result.get(self.mappings.iv.param)
                id = result.get(self.mappings.id.param)
                name = result.get(self.mappings.name.param).replace("\u2642", " M").replace("\u2640", " F")
                latitude = result.get(self.mappings.latitude.param)
                longitude = result.get(self.mappings.longitude.param)
                expiration = result.get(self.mappings.expiration.param)
                encounter = result.get(self.mappings.encounter.param)
                spawnpoint = result.get(self.mappings.spawnpoint.param)

                # If this is a composite param, split it ("coords": "-31.415553, -64.190480")
                if self.mappings.latitude.param == self.mappings.longitude.param:
                    position = result.get(self.mappings.latitude.param).replace(" ", "").split(",")
                    latitude = position[0]
                    longitude = position[1]

                # Format the time accordingly. Pokemon times are in milliseconds!
                if self.mappings.expiration.exists and expiration:
                    if self.mappings.expiration.format == SniperSourceMappingTimeFormat.SECONDS:
                        expiration = expiration * 1000
                    elif self.mappings.expiration.format == SniperSourceMappingTimeFormat.UTC:
                        utc_date = datetime.strptime(expiration.replace("T", " ")[:19], self.time_mask)
                        unix_timestamp = calendar.timegm(utc_date.timetuple())
                        local_date = datetime.fromtimestamp(unix_timestamp)
                        local_date = local_date.replace(microsecond=utc_date.microsecond)
                        expiration = time.mktime(local_date.timetuple()) * 1000
                else:
                    minutes_to_expire = 3
                    seconds_per_minute = 60
                    expiration = (time.time() + minutes_to_expire * seconds_per_minute) * 1000

                # If either name or ID are invalid, fix it using each other
                if not name or not id:
                    if not name and id:
                        name = Pokemons.name_for(id)
                    if not id and name:
                        id = Pokemons.id_for(name)

                # Some type castings were specified for a better readability
                pokemons.append({
                    'iv': int(iv or 0),
                    'pokemon_id': int(id or 0),
                    'pokemon_name': str(name or ''),
                    'latitude': float(latitude or .0),
                    'longitude': float(longitude or .0),
                    'expiration_timestamp_ms': long(expiration or 0),
                    'last_modified_timestamp_ms': long(expiration or 0),
                    'encounter_id': long(encounter or 0),
                    'spawn_point_id': str(spawnpoint or '')
                })
        except requests.exceptions.Timeout:
            raise Exception("Fetching has timed out")
        except requests.exceptions.ConnectionError:
            raise Exception("Source not available")
        except:
            raise

        return pokemons

    def validate(self):
        try:
            if self.enabled:
                errors = []
                data = self.fetch_raw()
                
                # Check whether the params really exist if they have been specified like so
                if data:
                    if self.mappings.iv.exists and self.mappings.iv.param not in data[0]:
                       errors.append(self.mappings.iv.param)
                    if self.mappings.id.exists and self.mappings.id.param not in data[0]:
                        errors.append(self.mappings.id.param)
                    if self.mappings.name.exists and self.mappings.name.param not in data[0]:
                        errors.append(self.mappings.name.param)
                    if self.mappings.latitude.exists and self.mappings.latitude.param not in data[0]:
                        errors.append(self.mappings.latitude.param)
                    if self.mappings.longitude.exists and self.mappings.longitude.param not in data[0]:
                        errors.append(self.mappings.longitude.param)
                    if self.mappings.expiration.exists and self.mappings.expiration.param not in data[0]:
                        errors.append(self.mappings.expiration.param)
                    if self.mappings.encounter.exists and self.mappings.encounter.param not in data[0]:
                        errors.append(self.mappings.encounter.param)
                    if self.mappings.spawnpoint.exists and self.mappings.spawnpoint.param not in data[0]:
                        errors.append(self.mappings.spawnpoint.param)

                    # All wrong mappings were gathered at once for a better usability (instead of raising multiple exceptions)
                    if errors:
                        raise LookupError("The following params dont exist: {}".format(", ".join(errors)))
                else:
                    raise ValueError("Empty reply")
            else:
                raise ValueError("Source is not enabled")
        except requests.exceptions.Timeout:
            raise ValueError("Fetching has timed out")
        except requests.exceptions.ConnectionError:
            raise ValueError("Source not available")
        except:
            raise

# Represents the JSON params mappings
class SniperSourceMapping(object):
    def __init__(self, mapping):
        self.iv = SniperSourceMappingValues(False, mapping.get('iv', {}))
        self.id = SniperSourceMappingValues(True, mapping.get('id', {}))
        self.name = SniperSourceMappingValues(True, mapping.get('name', {}))
        self.latitude = SniperSourceMappingValues(True, mapping.get('latitude', {}))
        self.longitude = SniperSourceMappingValues(True, mapping.get('longitude', {}))
        self.expiration = SniperSourceMappingValues(False, mapping.get('expiration', {}))
        self.encounter = SniperSourceMappingValues(False, mapping.get('encounter', {}))
        self.spawnpoint = SniperSourceMappingValues(False, mapping.get('spawnpoint', {}))

# Represents the JSON params mappings values
class SniperSourceMappingValues(object):
    def __init__(self, required, values):
        self.required = required
        self.param = values.get('param', '')
        self.format = values.get('format', SniperSourceMappingTimeFormat.DEFAULT)
        self.exists = values != {} and values.get('param') != None

        # Validate formats
        if self.format not in vars(SniperSourceMappingTimeFormat).values():
            raise ValueError('Unrecognized format: {}'.format(self.format))

# Represents the JSON time param formatting type
class SniperSourceMappingTimeFormat(object):
    NONE = ''
    UTC = 'utc'
    SECONDS = 'seconds'
    MILLISECONDS = 'milliseconds'
    DEFAULT = NONE

# Represents the information ordering types
class SniperOrderMode(object):
    IV = 'iv'
    VIP = 'vip'
    MISSING = 'missing'
    PRIORITY = 'priority'
    EXPIRATION = 'expiration_timestamp_ms'
    DEFAULT = [MISSING, VIP, PRIORITY]

# Represents the snipping type
class SniperMode(object):
    URL = 'url'
    SOCIAL = 'social'
    DEFAULT = SOCIAL

# Teleports the player to a target gotten from either social or a single/multiple URL sources
class Sniper(BaseTask):
    SUPPORTED_TASK_API_VERSION = 1
    MIN_SECONDS_ALLOWED_FOR_CELL_CHECK = 10
    MIN_SECONDS_ALLOWED_FOR_REQUESTING_DATA = 5
    MIN_BALLS_FOR_CATCHING = 25
    MAX_CACHE_LIST_SIZE = 300

    def __init__(self, bot, config):
        super(Sniper, self).__init__(bot, config)

    def initialize(self):
        self.vip_dictionary = {}
        self.catch_dictionary = {}
        self.last_cell_check_time = time.time()
        self.last_data_request_time = time.time()
        self.pokedex = inventory.pokedex()
        self.debug = self.config.get('debug', False)
        self.special_iv = self.config.get('special_iv', 100)
        self.bullets = self.config.get('bullets', 1)
        self.homing_shots = self.config.get('homing_shots', True)
        self.mode = self.config.get('mode', SniperMode.DEFAULT)
        self.order = self.config.get('order', SniperOrderMode.DEFAULT)
        self.altitude = uniform(self.bot.config.alt_min, self.bot.config.alt_max)
        self.sources_pending_validation = [SniperSource(data) for data in self.config.get('sources', [])]
        self.sources = []

        # Dont bother with validations/builds if task is not even enabled
        if self.enabled:
            # Allocate space on the global bot object to cache results. TODO: Use dict instead (faster lookup - O(1))
            if not hasattr(self.bot, "sniper_cache"):
                self.bot.sniper_cache = []

            # Validate ordering
            for ordering in self.order:
                if ordering not in vars(SniperOrderMode).values():
                    raise ValueError("Unrecognized ordering: '{}'".format(ordering))

            # Validate mode and sources
            if self.mode not in vars(SniperMode).values():
                raise ValueError("Unrecognized mode: '{}'".format(self.mode))

            # Build catchable dictionaries, where key = id and value = priority
            for key, value in self.config.get('catch', {}).iteritems():
                self.catch_dictionary[Pokemons.id_for(key)] = value
            for key, name in self.bot.config.vips.iteritems():
                self.vip_dictionary[Pokemons.id_for(key)] = 0

    def is_snipeable(self, pokemon):
        # Skip if already handled
        if self._is_cached(pokemon):
            self._trace('{} was already handled! Skipping...'.format(pokemon.get('pokemon_name')))
            return False

        # Skip if expired (cast milliseconds to seconds for comparision)
        if (pokemon.get('expiration_timestamp_ms', 0) or pokemon.get('last_modified_timestamp_ms', 0)) / 1000 < time.time():
            self._trace('{} is expired! Skipping...'.format(pokemon.get('pokemon_name')))
            return False

        # Skip if not in catch list, not a VIP and/or IV sucks (if any)
        if self.catch_dictionary.has_key(pokemon.get('pokemon_id', 0)):
            self._trace('{} is catchable!'.format(pokemon.get('pokemon_name')))
        else:
            # Not catchable. Having a good IV should suppress the not in catch/vip list (most important)
            if pokemon.get('iv', 0) and pokemon.get('iv', 0) < self.special_iv:
                self._trace('{} is not catchable, but has a decent IV!'.format(pokemon.get('pokemon_name')))
            else:
                # Not catchable and IV is not good enough (if any). Check VIP list
                if pokemon.get('vip', False):
                    self._trace('{} is not catchable and bad IV (if any), but its a VIP!'.format(pokemon.get('pokemon_name')))
                else:
                    if pokemon.get('missing', False):
                        self._trace('{} is not catchable, not VIP and bad IV (if any), but its a missing one.'.format(pokemon.get('pokemon_name')))
                    else:
                        self._trace('{} is not catchable, nor a VIP or a missing one and bad IV (if any). Skipping...'.format(pokemon.get('pokemon_name')))
                        return False

        return True

    # Snipe a target. This function admits that if a target really exists, it will be 'caught'.
    def snipe(self, pokemon):
        success = False

        # Apply snipping business rules and snipe if its good
        if not self.is_snipeable(pokemon):
            self._trace('{} is not snipeable! Skipping...'.format(pokemon['pokemon_name']))
        else:
            # Backup position before anything
            last_position = self.bot.position[0:2]

            # Teleport, so that we can see nearby stuff
            self.bot.hb_locked = True
            self._teleport_to(pokemon)

            # If social is enabled and if no verification is needed, trust it. Otherwise, update IDs!
            verify = not pokemon.get('encounter_id') or not pokemon.get('spawn_point_id')
            exists = not verify and self.mode == SniperMode.SOCIAL
            success = exists

            # If information verification have to be done, do so
            if verify:
                seconds_since_last_check = time.time() - self.last_cell_check_time

                # Wait a maximum of MIN_SECONDS_ALLOWED_FOR_CELL_CHECK seconds before requesting nearby cells
                if (seconds_since_last_check < self.MIN_SECONDS_ALLOWED_FOR_CELL_CHECK):
                    time.sleep(self.MIN_SECONDS_ALLOWED_FOR_CELL_CHECK - seconds_since_last_check)

                nearby_pokemons = []
                nearby_stuff = self.bot.get_meta_cell()
                self.last_cell_check_time = time.time()

                # Retrieve nearby pokemons for validation
                nearby_pokemons.extend(nearby_stuff.get('wild_pokemons', []))
                nearby_pokemons.extend(nearby_stuff.get('catchable_pokemons', []))

                # Make sure the target really/still exists (nearby_pokemon key names are game-bound!)
                for nearby_pokemon in nearby_pokemons:
                    nearby_pokemon_id = nearby_pokemon.get('pokemon_data', {}).get('pokemon_id') or nearby_pokemon.get('pokemon_id')

                    # If we found the target, it exists and will very likely be encountered/caught (success)
                    if nearby_pokemon_id == pokemon.get('pokemon_id', 0):
                        exists = True
                        success = True

                        # Also, if the IDs arent valid, override them (nearby_pokemon key names are game-bound!) with game values
                        if not pokemon.get('encounter_id') or not pokemon.get('spawn_point_id'):
                            pokemon['encounter_id'] = nearby_pokemon['encounter_id']
                            pokemon['spawn_point_id'] = nearby_pokemon['spawn_point_id']
                        break

            # If target exists, catch it, otherwise ignore
            if exists:
                self._log('Yay! There really is a wild {} nearby!'.format(pokemon.get('pokemon_name')))
                self._teleport_back_and_catch(last_position, pokemon)
            else:
                self._error('Damn! Its not here. Reasons: too far, caught, expired or fake data. Skipping...')
                self._teleport_back(last_position)

            # Save target and unlock heartbeat calls
            self._cache(pokemon)
            self.bot.hb_locked = False

        return success

    def work(self):
        if self._is_enabled():
            targets = []

            # Retrieve the targets
            if self.mode == SniperMode.SOCIAL:
                targets = self._get_pokemons_from_social()
            elif self.mode == SniperMode.URL:
                targets = self._get_pokemons_from_url()

            if targets:
                # Order the targets (descending)
                targets = sorted(targets, key=itemgetter(*self.order), reverse=True)
                shots = 0

                # For as long as there are targets available, try to snipe untill we run out of bullets
                for index, target in enumerate(targets):
                    if shots < self.bullets:
                        success = self.snipe(target)
                        shots += 1

                        # Homing shots are supposed to hit the target (capture). Rollback
                        if self.homing_shots and not success:
                            shots -= 1

                        # Wait a bit if were going to snipe again (bullets and targets left)
                        if shots < self.bullets and index < len(targets):
                            self._log('Waiting a few seconds to teleport again to another target...')
                            time.sleep(3)

        return WorkerResult.SUCCESS

    def _parse_pokemons(self, pokemon_dictionary_list):
        result = []

        # Build up the pokemon by adding unusual information (used in multiple purposes)
        for pokemon in pokemon_dictionary_list:
            pokemon['iv'] = pokemon.get('iv', 0)
            pokemon['pokemon_name'] = pokemon.get('pokemon_name', Pokemons.name_for(pokemon.get('pokemon_id')))
            pokemon['vip'] = self.vip_dictionary.has_key(pokemon.get('pokemon_id'))
            pokemon['missing'] = not self.pokedex.captured(pokemon.get('pokemon_id'))
            pokemon['priority'] = self.catch_dictionary.get(pokemon.get('pokemon_id'), 0)

            # Check whether this is a valid target
            if self.is_snipeable(pokemon):
                result.append(pokemon)

        return result

    def _get_pokemons_from_social(self):
        if not hasattr(self.bot, 'mqtt_pokemon_list') or not self.bot.mqtt_pokemon_list:
            return []

        self._trace('Social has returned {} pokemon(s)'.format(len(self.bot.mqtt_pokemon_list)))

        return self._parse_pokemons(self.bot.mqtt_pokemon_list)

    def _get_pokemons_from_url(self):
        results_hash_map = {}
        seconds_since_last_valid_request = time.time() - self.last_data_request_time

        # If something is requesting this info too fast, skip it (we might crash their servers)
        if (seconds_since_last_valid_request > self.MIN_SECONDS_ALLOWED_FOR_REQUESTING_DATA):
            self.last_data_request_time = time.time()

            self._trace("Fetching pokemons from the sources...")
            for source in self.sources:
                try:
                    source_pokemons = source.fetch()
                    self._trace("Source '{}' returned {} results".format(source.url, len(source_pokemons)))

                    # Merge lists, making sure to exclude repeated data. Use location as the hash key
                    for source_pokemon in source_pokemons:
                        key = self._hash(source_pokemon)

                        if not results_hash_map.has_key(key):
                            results_hash_map[key] = source_pokemon
                except Exception as exception:
                    self._error("Could not fetch data from '{}'. Details: {}. Skipping...".format(source.url, exception))
            self._trace("After merging, we've got {} results".format(len(results_hash_map.values())))
        else:
            self._trace("Not ready yet to retrieve data...")

        return self._parse_pokemons(results_hash_map.values())

    def _hash(self, pokemon):
        # Use approximate location instead, because some IDs might be wrong. The first 4 decimal places is enough for this
        return "{0:.4f};{1:.4f}".format(pokemon.get('latitude'), pokemon.get('longitude'))

    def _equals(self, pokemon_1, pokemon_2):
        return self._hash(pokemon_1) == self._hash(pokemon_2)

    def _validate_sources(self):
        # Create a copy of the list so we can iterate and remove elements at the same time
        for source in list(self.sources_pending_validation):
            try:
                if source.enabled:
                    source.validate()
                    self._log("Source '{}' is good! Storing...".format(source.url))
                    self.sources_pending_validation.remove(source)
                    self.sources.append(source)
                else:
                    self._log("Source '{}' is disabled! Ignoring...".format(source.url))
                    self.sources_pending_validation.remove(source)
            except LookupError as exception:
                self._error("Source '{}' contains errors. Details: {}. Ignoring...".format(source.url, exception))
                self.sources_pending_validation.remove(source)
            except ValueError as exception:
                self._error("Source '{}' could not be validated. Details: {}. Still pending...".format(source.url, exception))

    def _is_enabled(self):
        # Check if there are pending validations
        if self.sources_pending_validation:
            self._log("Validating sources: {}...".format(", ".join([source.url for source in self.sources_pending_validation])))
            self._validate_sources()

        # Check whether we have some snipe sources to snipe from or if catching has been disabled at all
        if not self.sources and not self.sources_pending_validation:
            self._error("There is no source available to snipe from. Skipping...")
            return False
        elif self.bot.catch_disabled:
            self._trace("All catching tasks are currently disabled until {}. Sniper will resume when catching tasks are re-enabled".format(self.bot.catch_resume_at.strftime("%H:%M:%S")))
            return False

        return True

    def _is_cached(self, pokemon):
        return self._hash(pokemon) in self.bot.sniper_cache

    def _cache(self, pokemon):
        if not self._is_cached(pokemon):
            # If cache is full, remove the first 25 registries (resource saving - too much comparisions)
            if len(self.bot.sniper_cache) >= self.MAX_CACHE_LIST_SIZE:
                del self.bot.sniper_cache[:25]
            self.bot.sniper_cache.append(self._hash(pokemon))

    def _log(self, message):
        self.emit_event('sniper_log', formatted='{message}', data={'message': message})

    def _error(self, message):
        self.emit_event('sniper_error', formatted='{message}', data={'message': message})

    def _trace(self, message):
        if self.debug:
            self._log(message)

    def _teleport(self, latitude, longitude, altitude):
        self.bot.api.set_position(latitude, longitude, altitude, True)
        time.sleep(3)

    def _teleport_to(self, pokemon):
        self.emit_event(
            'sniper_teleporting',
            formatted = 'Teleporting to meet {name} ({latitude}; {longitude})...',
            data = { 'name': pokemon['pokemon_name'], 'latitude': pokemon['latitude'], 'longitude': pokemon['longitude'] }
        )
        self._teleport(pokemon['latitude'], pokemon['longitude'], self.altitude)

    def _teleport_back(self, position_array):
        self.emit_event(
            'sniper_teleporting',
            formatted = 'Teleporting back to the old position ({latitude}; {longitude})...',
            data = { 'latitude': position_array[0], 'longitude': position_array[1] }
        )
        self._teleport(position_array[0], position_array[1], self.altitude)

    def _teleport_back_and_catch(self, position_array, pokemon):
        catch_worker = PokemonCatchWorker(pokemon, self.bot)
        api_encounter_response = catch_worker.create_encounter_api_call()
        self._teleport_back(position_array)
        catch_worker.work(api_encounter_response)