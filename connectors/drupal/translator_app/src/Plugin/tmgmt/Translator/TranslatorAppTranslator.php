<?php

namespace Drupal\translator_app\Plugin\tmgmt\Translator;

use Drupal\Component\Serialization\Json;
use Drupal\Core\StringTranslation\TranslatableMarkup;
use Drupal\tmgmt\Attribute\TranslatorPlugin;
use Drupal\tmgmt\JobInterface;
use Drupal\tmgmt\JobItemInterface;
use Drupal\tmgmt\Translator\AvailableResult;
use Drupal\tmgmt\TranslatorInterface;
use Drupal\tmgmt\TranslatorPluginBase;
use Drupal\translator_app\TranslatorAppTranslatorUi;
use GuzzleHttp\Exception\GuzzleException;

/**
 * Translator App provider for TMGMT.
 */
#[TranslatorPlugin(
  id: 'translator_app',
  label: new TranslatableMarkup('Translator App'),
  description: new TranslatableMarkup('Submits TMGMT jobs to the Translator App API.'),
  ui: TranslatorAppTranslatorUi::class,
  map_remote_languages: TRUE,
)]
class TranslatorAppTranslator extends TranslatorPluginBase {

  /**
   * {@inheritdoc}
   */
  protected $escapeStart = '[[TRANSLATOR_APP_ESCAPE:';

  /**
   * {@inheritdoc}
   */
  protected $escapeEnd = ']]';

  /**
   * {@inheritdoc}
   */
  public function defaultSettings() {
    return [
      'api_base_url' => '',
      'api_key' => '',
      'translation_provider' => '',
      'translation_model' => '',
      'request_timeout' => 90,
      'translate_as_html' => TRUE,
    ];
  }

  /**
   * {@inheritdoc}
   */
  public function checkAvailable(TranslatorInterface $translator) {
    if (!$this->getTranslatorSetting($translator, 'api_base_url') || !$this->getTranslatorSetting($translator, 'api_key')) {
      return AvailableResult::no(t('Translator App API base URL and API key are required.'));
    }

    return AvailableResult::yes();
  }

  /**
   * {@inheritdoc}
   */
  public function getDefaultRemoteLanguagesMappings() {
    return [
      'en' => 'en',
      'es' => 'es',
      'fr' => 'fr',
      'de' => 'de',
      'ar' => 'ar',
      'bn' => 'bn',
      'hi' => 'hi',
      'it' => 'it',
      'pt' => 'pt',
      'ja' => 'ja',
      'zh' => 'zh',
    ];
  }

  /**
   * {@inheritdoc}
   */
  public function getSupportedRemoteLanguages(TranslatorInterface $translator) {
    $languages = [
      'en',
      'es',
      'fr',
      'de',
      'ar',
      'bn',
      'hi',
      'it',
      'pt',
      'ja',
      'zh',
    ];

    return array_combine($languages, $languages);
  }

  /**
   * {@inheritdoc}
   */
  public function getSupportedTargetLanguages(TranslatorInterface $translator, $source_language) {
    $languages = $this->getSupportedRemoteLanguages($translator);
    unset($languages[$source_language]);
    return $languages;
  }

  /**
   * {@inheritdoc}
   */
  public function requestTranslation(JobInterface $job) {
    $translator = $job->getTranslator();
    if (!$this->getTranslatorSetting($translator, 'api_base_url') || !$this->getTranslatorSetting($translator, 'api_key')) {
      $job->rejected('Translator App API base URL and API key are required.');
      return FALSE;
    }

    $job->submitted('Translator App translation job has been submitted.');

    /** @var \Drupal\tmgmt\Data $data_service */
    $data_service = \Drupal::service('tmgmt.data');
    $translated_items = 0;

    foreach ($job->getItems() as $job_item) {
      $job_item->active('Sending source text to Translator App.', [], 'debug');
      $translatable_data = $data_service->filterTranslatable($job_item->getData());
      $translated_data = [];

      foreach ($translatable_data as $key => $data_item) {
        if (empty($data_item['#text'])) {
          continue;
        }

        try {
          $translated_text = $this->translateDataItem($job, $job_item, $key, $data_item);
        }
        catch (\Exception $exception) {
          $job_item->addMessage('Translator App failed for data item @key: @message', [
            '@key' => $key,
            '@message' => $exception->getMessage(),
          ], 'error');
          $job->addMessage('Translator App failed for job item @item: @message', [
            '@item' => $job_item->id(),
            '@message' => $exception->getMessage(),
          ], 'error');
          return FALSE;
        }

        $translated_data[$key] = [
          '#text' => $this->unescapeText($translated_text),
        ];
      }

      if ($translated_data) {
        $job_item->addTranslatedData(
          $data_service->unflatten($translated_data),
          [],
          TMGMT_DATA_ITEM_STATE_TRANSLATED
        );
        $translated_items++;
      }
    }

    $job->addMessage('Translator App returned translations for @count job item(s).', [
      '@count' => $translated_items,
    ]);
  }

  /**
   * Sends one flattened TMGMT data item to Translator App.
   */
  protected function translateDataItem(JobInterface $job, JobItemInterface $job_item, string $key, array $data_item): string {
    $text = $this->escapeText($data_item);
    $format = $this->useHtmlEndpoint($job, $text) ? 'html' : 'text';
    $endpoint = $format === 'html' ? '/api/v1/translate/html' : '/api/v1/translate';
    $translator = $job->getTranslator();

    $payload = [
      'external_content_id' => 'drupal-tmgmt-job-' . $job->id() . '-item-' . $job_item->id() . '-' . md5($key),
      'content_type' => 'tmgmt:' . $job_item->getPlugin() . ':' . $job_item->getItemType(),
      'title' => $job->label(),
      'source_language' => $job->getRemoteSourceLanguage(),
      'target_language' => $job->getRemoteTargetLanguage(),
      'format' => $format,
      'text' => $text,
      'metadata' => [
        'drupal_tmgmt_job_id' => $job->id(),
        'drupal_tmgmt_job_item_id' => $job_item->id(),
        'drupal_tmgmt_item_type' => $job_item->getItemType(),
        'drupal_tmgmt_item_id' => $job_item->getItemId(),
        'drupal_tmgmt_data_key' => $key,
        'drupal_source_language' => $job->getSourceLangcode(),
        'drupal_target_language' => $job->getTargetLangcode(),
      ],
    ];

    $provider = $this->getJobSetting($job, 'translation_provider');
    $model = $this->getJobSetting($job, 'translation_model');
    if ($provider) {
      $payload['provider'] = $provider;
    }
    if ($model) {
      $payload['model'] = $model;
    }

    try {
      $response = \Drupal::httpClient()->post($this->apiBaseUrl($translator) . $endpoint, [
        'headers' => [
          'Content-Type' => 'application/json',
          'X-API-Key' => $this->getTranslatorSetting($translator, 'api_key'),
        ],
        'json' => $payload,
        'timeout' => (float) ($this->getJobSetting($job, 'request_timeout') ?: 90),
        'http_errors' => FALSE,
      ]);
    }
    catch (GuzzleException $exception) {
      throw new \RuntimeException($exception->getMessage(), 0, $exception);
    }

    $decoded = Json::decode((string) $response->getBody());
    if ($response->getStatusCode() >= 400) {
      $message = is_array($decoded) && !empty($decoded['detail']) ? $decoded['detail'] : 'Translator App API request failed.';
      throw new \RuntimeException($message);
    }
    if (!is_array($decoded) || empty($decoded['translated_text'])) {
      throw new \RuntimeException('Translator App API did not return translated_text.');
    }

    return $decoded['translated_text'];
  }

  /**
   * Decides whether to use HTML-safe translation for the current item.
   */
  protected function useHtmlEndpoint(JobInterface $job, string $text): bool {
    $setting = $this->getJobSetting($job, 'translate_as_html');
    if ($setting) {
      return TRUE;
    }

    return $text !== strip_tags($text);
  }

  /**
   * Returns a translator setting with fallback to the standalone module config.
   */
  protected function getTranslatorSetting(TranslatorInterface $translator, string $name, $default = '') {
    $value = $translator->getSetting($name);
    if ($value !== NULL && $value !== '') {
      return $value;
    }

    $config_value = \Drupal::config('translator_app.settings')->get($name);
    return ($config_value !== NULL && $config_value !== '') ? $config_value : $default;
  }

  /**
   * Returns a job setting with fallback to the translator and module config.
   */
  protected function getJobSetting(JobInterface $job, string $name, $default = '') {
    $value = $job->getSetting($name);
    if ($value !== NULL && $value !== '') {
      return $value;
    }

    return $this->getTranslatorSetting($job->getTranslator(), $name, $default);
  }

  /**
   * Returns the normalized API base URL for a translator.
   */
  protected function apiBaseUrl(TranslatorInterface $translator): string {
    return rtrim((string) $this->getTranslatorSetting($translator, 'api_base_url'), '/');
  }

}
