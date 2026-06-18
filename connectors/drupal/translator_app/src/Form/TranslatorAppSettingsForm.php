<?php

namespace Drupal\translator_app\Form;

use Drupal\Core\Form\ConfigFormBase;
use Drupal\Core\Form\FormStateInterface;

class TranslatorAppSettingsForm extends ConfigFormBase {

  protected function getEditableConfigNames() {
    return ['translator_app.settings'];
  }

  public function getFormId() {
    return 'translator_app_settings_form';
  }

  public function buildForm(array $form, FormStateInterface $form_state) {
    $config = $this->config('translator_app.settings');

    $form['api_base_url'] = [
      '#type' => 'url',
      '#title' => $this->t('API base URL'),
      '#default_value' => $config->get('api_base_url') ?: 'http://127.0.0.1:8000',
      '#required' => TRUE,
    ];
    $form['api_key'] = [
      '#type' => 'password',
      '#title' => $this->t('API key'),
      '#description' => $this->t('Leave blank to keep the current key.'),
    ];
    $form['source_language'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Source language'),
      '#default_value' => $config->get('source_language') ?: 'en',
      '#required' => TRUE,
    ];
    $form['target_language'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Target language'),
      '#default_value' => $config->get('target_language') ?: 'es',
      '#required' => TRUE,
    ];
    $form['translation_provider'] = [
      '#type' => 'select',
      '#title' => $this->t('Translation provider'),
      '#options' => [
        '' => $this->t('Server default'),
        'nllb' => $this->t('NLLB'),
        'openai' => $this->t('OpenAI'),
        'gemini' => $this->t('Gemini'),
        'libretranslate' => $this->t('LibreTranslate'),
        'demo' => $this->t('Demo'),
      ],
      '#default_value' => $config->get('translation_provider') ?: '',
    ];
    $form['translation_model'] = [
      '#type' => 'textfield',
      '#title' => $this->t('Model override'),
      '#default_value' => $config->get('translation_model') ?: '',
      '#description' => $this->t('Leave blank to use the provider default.'),
    ];

    return parent::buildForm($form, $form_state);
  }

  public function submitForm(array &$form, FormStateInterface $form_state) {
    $config = $this->config('translator_app.settings');
    $config
      ->set('api_base_url', rtrim($form_state->getValue('api_base_url'), '/'))
      ->set('source_language', $form_state->getValue('source_language'))
      ->set('target_language', $form_state->getValue('target_language'))
      ->set('translation_provider', $form_state->getValue('translation_provider'))
      ->set('translation_model', $form_state->getValue('translation_model'));

    if ($form_state->getValue('api_key')) {
      $config->set('api_key', $form_state->getValue('api_key'));
    }

    $config->save();
    parent::submitForm($form, $form_state);
  }
}
