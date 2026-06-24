<?php

namespace Drupal\translator_app;

use Drupal\Core\Form\FormStateInterface;
use Drupal\tmgmt\JobInterface;
use Drupal\tmgmt\TranslatorPluginUiBase;

/**
 * TMGMT provider UI for Translator App.
 */
class TranslatorAppTranslatorUi extends TranslatorPluginUiBase {

  /**
   * {@inheritdoc}
   */
  public function buildConfigurationForm(array $form, FormStateInterface $form_state) {
    $form = parent::buildConfigurationForm($form, $form_state);

    /** @var \Drupal\tmgmt\TranslatorInterface $translator */
    $translator = $form_state->getFormObject()->getEntity();
    $global_config = \Drupal::config('translator_app.settings');

    $form['api_base_url'] = [
      '#type' => 'url',
      '#title' => t('Translator App API base URL'),
      '#default_value' => $translator->getSetting('api_base_url') ?: $global_config->get('api_base_url') ?: 'http://127.0.0.1:8000',
      '#required' => TRUE,
    ];
    $form['api_key'] = [
      '#type' => 'password',
      '#title' => t('Translator App API key'),
      '#default_value' => $translator->getSetting('api_key') ?: $global_config->get('api_key') ?: '',
      '#required' => TRUE,
      '#description' => t('Use a Translator App integration API key. Do not enter OpenAI, Gemini, or other provider keys here.'),
    ];
    $form['translation_provider'] = [
      '#type' => 'select',
      '#title' => t('Translation provider'),
      '#options' => [
        '' => t('Server default'),
        'nllb' => t('NLLB'),
        'openai' => t('OpenAI'),
        'gemini' => t('Gemini'),
        'libretranslate' => t('LibreTranslate'),
        'demo' => t('Demo'),
      ],
      '#default_value' => $translator->getSetting('translation_provider') ?: $global_config->get('translation_provider') ?: '',
    ];
    $form['translation_model'] = [
      '#type' => 'textfield',
      '#title' => t('Model override'),
      '#default_value' => $translator->getSetting('translation_model') ?: $global_config->get('translation_model') ?: '',
      '#description' => t('Leave blank to use the Translator App server default for the selected provider.'),
    ];
    $form['translate_as_html'] = [
      '#type' => 'checkbox',
      '#title' => t('Use HTML-safe translation for all TMGMT text fields'),
      '#default_value' => $translator->getSetting('translate_as_html') !== NULL ? $translator->getSetting('translate_as_html') : TRUE,
      '#description' => t('Recommended for Drupal content because formatted text fields, links, and placeholders need to be preserved.'),
    ];
    $form['request_timeout'] = [
      '#type' => 'number',
      '#title' => t('Request timeout seconds'),
      '#default_value' => $translator->getSetting('request_timeout') ?: 90,
      '#min' => 5,
      '#max' => 600,
      '#step' => 1,
      '#required' => TRUE,
    ];

    return $form;
  }

  /**
   * {@inheritdoc}
   */
  public function checkoutSettingsForm(array $form, FormStateInterface $form_state, JobInterface $job) {
    $form['translation_provider'] = [
      '#type' => 'select',
      '#title' => t('Translation provider'),
      '#options' => [
        '' => t('Provider default'),
        'nllb' => t('NLLB'),
        'openai' => t('OpenAI'),
        'gemini' => t('Gemini'),
        'libretranslate' => t('LibreTranslate'),
        'demo' => t('Demo'),
      ],
      '#default_value' => $job->getTranslator()->getSetting('translation_provider') ?: '',
    ];
    $form['translation_model'] = [
      '#type' => 'textfield',
      '#title' => t('Model override'),
      '#default_value' => $job->getTranslator()->getSetting('translation_model') ?: '',
    ];
    $form['translate_as_html'] = [
      '#type' => 'checkbox',
      '#title' => t('Use HTML-safe translation'),
      '#default_value' => $job->getTranslator()->getSetting('translate_as_html') !== NULL ? $job->getTranslator()->getSetting('translate_as_html') : TRUE,
    ];

    return $form;
  }

}
